import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:80], s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("tpf.c", [
    ('''        case VSIR_OP_BREAK:
        case VSIR_OP_CASE:
        case VSIR_OP_CONTINUE:
        case VSIR_OP_COUNTBITS:
''', '''        case VSIR_OP_BREAK:
        case VSIR_OP_BREAKP:
        case VSIR_OP_CASE:
        case VSIR_OP_CONTINUE:
        case VSIR_OP_CONTINUEP:
        case VSIR_OP_COUNTBITS:
'''),
])

edit("ir.c", [
    ('''static enum vkd3d_result vsir_program_forward_destinations(struct vsir_program *program)
{''', '''static bool vsir_opcode_is_conditional(enum vsir_opcode opcode)
{
    return opcode == VSIR_OP_IF || opcode == VSIR_OP_BREAKP || opcode == VSIR_OP_CONTINUEP
            || opcode == VSIR_OP_DISCARD;
}

static unsigned int forward_skip_nops(struct vsir_instruction **list, unsigned int count, unsigned int index)
{
    while (index < count && list[index]->opcode == VSIR_OP_NOP)
        ++index;
    return index;
}

/* fxc2: the conditional instructions of shader model 4 test for zero as
 * readily as for nonzero, and a break or continue can carry its own
 * condition:
 *
 *     not sr2.x, sr1.x        if_nz sr1.x
 *     if_nz sr2.x                 break
 *                             endif
 *
 * become "if_z sr1.x" and "breakc_nz sr1.x". */
static void vsir_program_fold_conditionals(struct vsir_program *program, struct vsir_instruction **list,
        unsigned int count, const struct forward_ssa *ssa)
{
    if (program->shader_version.major < 4)
        return;

    for (unsigned int i = 0; i < count; ++i)
    {
        struct vsir_instruction *ins = list[i], *def;
        struct vsir_src_operand *src;
        unsigned int jump, end;

        if (!vsir_opcode_is_conditional(ins->opcode) || ins->src_count != 1)
            continue;
        src = &ins->src[0];

        /* A logical not is emitted as a bitwise one, booleans being 0 or ~0. */
        if (src->reg.type == VSIR_REGISTER_SSA && !src->modifiers
                && (def = ssa[src->reg.idx[0].offset].def) && def->opcode == VSIR_OP_NOT
                && ssa[src->reg.idx[0].offset].use_count == 1
                && def->dst[0].reg.type == VSIR_REGISTER_SSA
                && def->dst[0].reg.idx[0].offset == src->reg.idx[0].offset && !def->dst[0].modifiers
                && def->src[0].reg.type == VSIR_REGISTER_SSA && !def->src[0].modifiers
                && (def->dst[0].write_mask & (1u << vsir_swizzle_get_component(src->swizzle, 0))))
        {
            unsigned int component = vsir_swizzle_get_component(def->src[0].swizzle,
                    vsir_swizzle_get_component(src->swizzle, 0));
            enum vsir_data_type data_type = src->reg.data_type;
            uint32_t swizzle = 0;

            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
                vsir_swizzle_set_component(&swizzle, j, component);
            src->reg = def->src[0].reg;
            src->reg.data_type = data_type;
            src->swizzle = swizzle;
            ins->flags = ins->flags == VKD3D_SHADER_CONDITIONAL_OP_NZ
                    ? VKD3D_SHADER_CONDITIONAL_OP_Z : VKD3D_SHADER_CONDITIONAL_OP_NZ;
            vsir_instruction_make_nop(def);
        }

        if (ins->opcode != VSIR_OP_IF)
            continue;
        jump = forward_skip_nops(list, count, i + 1);
        if (jump >= count || (list[jump]->opcode != VSIR_OP_BREAK && list[jump]->opcode != VSIR_OP_CONTINUE))
            continue;
        end = forward_skip_nops(list, count, jump + 1);
        if (end >= count || list[end]->opcode != VSIR_OP_ENDIF)
            continue;
        ins->opcode = list[jump]->opcode == VSIR_OP_BREAK ? VSIR_OP_BREAKP : VSIR_OP_CONTINUEP;
        vsir_instruction_make_nop(list[jump]);
        vsir_instruction_make_nop(list[end]);
    }
}

static enum vkd3d_result vsir_program_forward_destinations(struct vsir_program *program)
{'''),
    ('''    vkd3d_free(ssa);
    vkd3d_free(list);
    return VKD3D_OK;
}

/* This pass does two things:''', '''    vsir_program_fold_conditionals(program, list, count, ssa);

    vkd3d_free(ssa);
    vkd3d_free(list);
    return VKD3D_OK;
}

/* This pass does two things:'''),
])
print("patched")
