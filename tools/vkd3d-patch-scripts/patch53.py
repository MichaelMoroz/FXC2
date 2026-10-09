import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/ir.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


PASS = r'''/* fxc2: a field of a word is a shift and a mask in HLSL and one instruction in
 * shader model 5:
 *
 *     ushr sr1.x, sr0.x, l(15)
 *     and sr2.x, sr1.x, l(31)            ubfe sr2.x, l(5), l(15), sr0.x
 *
 * FXC makes the same choice. Code that takes words apart (a decoder, a hash, a
 * packed format) is a quarter of this. VKD3D_UBFE=0 keeps the two. */
static void vsir_program_fold_bitfield_extracts(struct vsir_program *program, struct vsir_instruction **list,
        unsigned int count, struct forward_ssa *ssa)
{
    const char *env;

    if (program->shader_version.major < 5 || ((env = getenv("VKD3D_UBFE")) && !strcmp(env, "0")))
        return;

    for (unsigned int i = 0; i < count; ++i)
    {
        struct vsir_instruction *ins = list[i];
        unsigned int comp = 0;
        uint32_t write_mask;

        if (ins->opcode != VSIR_OP_AND || ins->dst_count != 1 || ins->src_count != 2 || ins->dst[0].modifiers)
            continue;
        write_mask = ins->dst[0].write_mask;
        if (!write_mask || (write_mask & (write_mask - 1)))
            continue;
        while (!(write_mask & (1u << comp)))
            ++comp;

        for (unsigned int k = 0; k < 2; ++k)
        {
            const struct vsir_src_operand *value = &ins->src[k], *imm = &ins->src[!k], *shift, *source;
            struct vsir_src_operand source_copy;
            struct vkd3d_shader_location location;
            unsigned int id, c, source_component;
            struct vsir_dst_operand dst;
            struct vsir_instruction *def;
            uint32_t mask, width, offset;

            if (imm->reg.type != VSIR_REGISTER_IMMCONST || imm->reg.dimension == VSIR_DIMENSION_VEC4
                    || !forward_is_plain_value(value))
                continue;
            mask = imm->reg.u.immconst_u32[0];
            if (!mask || mask == ~0u || (mask & (mask + 1)))
                continue;
            for (width = 0; mask >> width; ++width)
                ;

            id = value->reg.idx[0].offset;
            if (!(def = ssa[id].def) || def->opcode != VSIR_OP_USHR || ssa[id].def_index >= i
                    || ssa[id].use_count != 1 || def->dst_count != 1 || def->src_count != 2
                    || def->dst[0].modifiers || def->dst[0].reg.type != VSIR_REGISTER_SSA
                    || def->dst[0].reg.idx[0].offset != id)
                continue;
            c = vsir_swizzle_get_component(value->swizzle, comp);
            if (!(def->dst[0].write_mask & (1u << c)))
                continue;
            shift = &def->src[1];
            source = &def->src[0];
            if (shift->reg.type != VSIR_REGISTER_IMMCONST || shift->reg.dimension == VSIR_DIMENSION_VEC4
                    || !forward_is_plain_value(source))
                continue;
            offset = shift->reg.u.immconst_u32[0] & 31;
            if (!offset)
                continue;
            if (offset + width > 32)
                width = 32 - offset;
            source_component = vsir_swizzle_get_component(source->swizzle, c);

            dst = ins->dst[0];
            source_copy = *source;
            location = ins->location;
            if (!vsir_instruction_init_with_params(program, ins, &location, VSIR_OP_UBFE, 1, 3))
                return;
            ins->dst[0] = dst;
            vsir_src_operand_init_const_u32(&ins->src[0], width);
            vsir_src_operand_init_const_u32(&ins->src[1], offset);
            ins->src[2] = source_copy;
            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
                vsir_swizzle_set_component(&ins->src[2].swizzle, j, source_component);
            /* The shift's use of its source is this instruction's now. */
            ssa[id].use_count = 0;
            vsir_instruction_make_nop(def);
            break;
        }
    }
}

'''
anchor = "static void vsir_program_simplify_conditions(struct vsir_program *program, struct vsir_instruction **list,"
rep(anchor, PASS + anchor)
rep('''    vsir_program_simplify_conditions(program, list, count, ssa);
''', '''    vsir_program_fold_bitfield_extracts(program, list, count, ssa);
    vsir_program_simplify_conditions(program, list, count, ssa);
''')
open(p, "w").write(s)

# the bytecode writer's list of instructions it writes as they are
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/tpf.c")
s = open(p).read()
rep("""        case VSIR_OP_USHR:
        case VSIR_OP_UTOF:
        case VSIR_OP_XOR:
            tpf_simple_instruction(tpf, ins);""", """        case VSIR_OP_UBFE:
        case VSIR_OP_USHR:
        case VSIR_OP_UTOF:
        case VSIR_OP_XOR:
            tpf_simple_instruction(tpf, ins);""")
open(p, "w").write(s)
print("patched")
