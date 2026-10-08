import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/ir.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


PASS = r'''/* fxc2: conditions are tested for "not zero" by the instruction that uses them
 * (if, breakc, movc, per component), so turning a value into a boolean first
 * is work for nothing:
 *
 *     and sr1.x, sr0.x, l(0x80000000)
 *     ine sr2.x, sr1.x, l(0)             and sr1.x, sr0.x, l(0x80000000)
 *     movc sr3.x, sr2.x, a, b            movc sr3.x, sr1.x, a, b
 *
 * The same goes for "x == 0" (the test or the two choices are swapped), for
 * "c ? 1 : 0" used as a condition again, and for "b & 1" of a comparison's
 * result. Integer code written with masks and ?: is full of these, and the GPU
 * runs what it is given one instruction after the other. */
static bool vsir_opcode_is_comparison(enum vsir_opcode opcode)
{
    switch (opcode)
    {
        case VSIR_OP_EQO:
        case VSIR_OP_EQU:
        case VSIR_OP_GEO:
        case VSIR_OP_GEU:
        case VSIR_OP_IEQ:
        case VSIR_OP_IGE:
        case VSIR_OP_ILT:
        case VSIR_OP_INE:
        case VSIR_OP_LTO:
        case VSIR_OP_LTU:
        case VSIR_OP_NEO:
        case VSIR_OP_NEU:
        case VSIR_OP_UGE:
        case VSIR_OP_ULT:
            return true;

        default:
            return false;
    }
}

/* Whether the components "used" of an immediate are all zero, or all not. */
static bool forward_immediate_is(const struct vsir_src_operand *src, uint32_t used, bool zero)
{
    if (src->reg.type != VSIR_REGISTER_IMMCONST)
        return false;
    for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
    {
        uint32_t value;

        if (!(used & (1u << j)))
            continue;
        value = src->reg.u.immconst_u32[src->reg.dimension == VSIR_DIMENSION_VEC4 ? j : 0];
        if (!value != zero)
            return false;
    }
    return true;
}

static bool forward_is_plain_value(const struct vsir_src_operand *src)
{
    return src->reg.type == VSIR_REGISTER_SSA && !src->modifiers && src->reg.dimension == VSIR_DIMENSION_VEC4;
}

/* If "def" computes nothing but whether one of its operands is zero, returns
 * that operand; "inverted" says which way round. "used" are the components
 * of the result that the condition looks at. */
static const struct vsir_src_operand *forward_condition_source(const struct vsir_instruction *def,
        const struct forward_ssa *ssa, uint32_t used, bool *inverted)
{
    const struct vsir_instruction *other;

    if (def->dst_count != 1 || def->dst[0].modifiers || (def->dst[0].write_mask & used) != used)
        return NULL;

    switch (def->opcode)
    {
        case VSIR_OP_INE:
        case VSIR_OP_IEQ:
            *inverted = def->opcode == VSIR_OP_IEQ;
            if (forward_immediate_is(&def->src[1], used, true) && forward_is_plain_value(&def->src[0]))
                return &def->src[0];
            if (forward_immediate_is(&def->src[0], used, true) && forward_is_plain_value(&def->src[1]))
                return &def->src[1];
            return NULL;

        case VSIR_OP_MOVC:
            if (!forward_is_plain_value(&def->src[0]))
                return NULL;
            if (forward_immediate_is(&def->src[1], used, false) && forward_immediate_is(&def->src[2], used, true))
                *inverted = false;
            else if (forward_immediate_is(&def->src[1], used, true) && forward_immediate_is(&def->src[2], used, false))
                *inverted = true;
            else
                return NULL;
            return &def->src[0];

        case VSIR_OP_AND:
            /* A comparison gives 0 or ~0: any bits of it say as much as all. */
            *inverted = false;
            for (unsigned int k = 0; k < 2; ++k)
            {
                if (!forward_immediate_is(&def->src[!k], used, false) || !forward_is_plain_value(&def->src[k]))
                    continue;
                other = ssa[def->src[k].reg.idx[0].offset].def;
                if (other && other->dst_count == 1 && vsir_opcode_is_comparison(other->opcode))
                    return &def->src[k];
            }
            return NULL;

        default:
            return NULL;
    }
}

static void vsir_program_simplify_conditions(struct vsir_program *program, struct vsir_instruction **list,
        unsigned int count, struct forward_ssa *ssa)
{
    const char *env;

    if (program->shader_version.major < 4 || ((env = getenv("VKD3D_SIMPLIFY_CONDITIONS")) && !strcmp(env, "0")))
        return;

    for (unsigned int i = 0; i < count; ++i)
    {
        struct vsir_instruction *ins = list[i];
        bool select = ins->opcode == VSIR_OP_MOVC;
        struct vsir_src_operand *src;

        if (!select && !(vsir_opcode_is_conditional(ins->opcode) && ins->src_count == 1))
            continue;
        if (select && (ins->dst_count != 1 || ins->src_count != 3))
            continue;
        src = &ins->src[0];

        for (unsigned int depth = 0; depth < 8; ++depth)
        {
            const struct vsir_src_operand *source;
            enum vsir_data_type data_type;
            uint32_t used = 0, swizzle = 0;
            struct vsir_instruction *def;
            unsigned int id, first = 0;
            bool inverted;

            if (!forward_is_plain_value(src))
                break;
            id = src->reg.idx[0].offset;
            if (!(def = ssa[id].def) || def->opcode == VSIR_OP_NOP || ssa[id].def_index >= i
                    || def->dst_count != 1 || def->dst[0].reg.type != VSIR_REGISTER_SSA
                    || def->dst[0].reg.idx[0].offset != id)
                break;
            /* The components of the condition that are looked at, as components of its value. */
            if (select)
            {
                for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
                {
                    if (ins->dst[0].write_mask & (1u << j))
                        used |= 1u << vsir_swizzle_get_component(src->swizzle, j);
                }
            }
            else
            {
                used = 1u << vsir_swizzle_get_component(src->swizzle, 0);
            }
            if (!used || !(source = forward_condition_source(def, ssa, used, &inverted)))
                break;

            while (!(used & (1u << first)))
                ++first;
            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
            {
                unsigned int component = vsir_swizzle_get_component(src->swizzle, j);

                if (!(used & (1u << component)))
                    component = first;
                vsir_swizzle_set_component(&swizzle, j, vsir_swizzle_get_component(source->swizzle, component));
            }
            ++ssa[source->reg.idx[0].offset].use_count;
            data_type = src->reg.data_type;
            src->reg = source->reg;
            src->reg.data_type = data_type;
            src->swizzle = swizzle;
            if (inverted)
            {
                if (select)
                {
                    struct vsir_src_operand tmp = ins->src[1];

                    ins->src[1] = ins->src[2];
                    ins->src[2] = tmp;
                }
                else
                {
                    ins->flags = ins->flags == VKD3D_SHADER_CONDITIONAL_OP_NZ
                            ? VKD3D_SHADER_CONDITIONAL_OP_Z : VKD3D_SHADER_CONDITIONAL_OP_NZ;
                }
            }
            if (!--ssa[id].use_count)
            {
                /* What the conversion read is no longer read by it. */
                for (unsigned int k = 0; k < def->src_count; ++k)
                {
                    if (def->src[k].reg.type == VSIR_REGISTER_SSA && ssa[def->src[k].reg.idx[0].offset].use_count)
                        --ssa[def->src[k].reg.idx[0].offset].use_count;
                }
                vsir_instruction_make_nop(def);
            }
        }
    }
}

'''
anchor = "static enum vkd3d_result vsir_program_forward_destinations(struct vsir_program *program)\n{"
rep(anchor, PASS + anchor)
rep('''    vsir_program_fold_conditionals(program, list, count, ssa);
''', '''    vsir_program_simplify_conditions(program, list, count, ssa);
    vsir_program_fold_conditionals(program, list, count, ssa);
''')
open(p, "w").write(s)
print("patched")
