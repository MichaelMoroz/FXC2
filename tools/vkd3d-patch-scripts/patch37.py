import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")
path = base + "ir.c"
s = open(path).read()

start = s.index("static bool forward_source(struct vsir_instruction **list")
end = s.index("static bool vsir_opcode_is_conditional")

NEW = r'''static unsigned int forward_count_uses(const struct vsir_instruction *ins, unsigned int id, bool *awkward)
{
    unsigned int uses = 0;

    for (unsigned int i = 0; i < ins->src_count; ++i)
    {
        const struct vsir_src_operand *src = &ins->src[i];

        /* As an array index it would need its swizzle looking at. */
        if (forward_count_ssa_in_indices(&src->reg, id))
            *awkward = true;
        if (src->reg.type != VSIR_REGISTER_SSA || src->reg.idx[0].offset != id)
            continue;
        if (src->reg.dimension != VSIR_DIMENSION_VEC4)
            *awkward = true;
        ++uses;
    }
    for (unsigned int i = 0; i < ins->dst_count; ++i)
    {
        if (forward_count_ssa_in_indices(&ins->dst[i].reg, id))
            *awkward = true;
    }
    return uses;
}

static bool forward_source(struct vsir_instruction **list, unsigned int count, unsigned int index,
        struct forward_ssa *ssa)
{
    struct vsir_instruction *mov = list[index];
    unsigned int id = mov->dst[0].reg.idx[0].offset, temp = mov->src[0].reg.idx[0].offset;
    /* A copy of a value, "mov sr2.x, sr1.wxxx", is how a swizzle comes out.
     * A value never changes, so that one holds wherever it is used. */
    bool value = mov->src[0].reg.type == VSIR_REGISTER_SSA;
    unsigned int remaining = ssa[id].use_count, uses = remaining, end, last = index, first = 0;

    if (!remaining)
        return false;
    while (!(mov->dst[0].write_mask & (1u << first)))
        ++first;

    /* Uses the copy cannot be shown to hold for keep it; the others still
     * need not wait for it. */
    for (end = index + 1; end < count && (value || end - index <= 64); ++end)
    {
        const struct vsir_instruction *ins = list[end];
        bool awkward = false;
        unsigned int n;

        n = forward_count_uses(ins, id, &awkward);
        if (awkward)
            break;
        remaining -= n;
        last = end;
        if (!remaining)
            break;
        if (!value && (vsir_opcode_is_block_boundary(ins->opcode) || vsir_instruction_writes_temp(ins, temp)))
            break;
    }

    for (unsigned int k = index + 1; k <= last; ++k)
    {
        struct vsir_instruction *ins = list[k];

        for (unsigned int i = 0; i < ins->src_count; ++i)
        {
            struct vsir_src_operand *src = &ins->src[i];
            enum vsir_data_type data_type = src->reg.data_type;
            uint32_t swizzle = 0;

            if (src->reg.type != VSIR_REGISTER_SSA || src->reg.idx[0].offset != id)
                continue;
            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
            {
                unsigned int component = vsir_swizzle_get_component(src->swizzle, j);

                /* Components the copy does not have can be named where they
                 * are not used. */
                if (!(mov->dst[0].write_mask & (1u << component)))
                    component = first;
                vsir_swizzle_set_component(&swizzle, j, vsir_swizzle_get_component(mov->src[0].swizzle, component));
            }
            src->reg = mov->src[0].reg;
            src->reg.data_type = data_type;
            src->swizzle = swizzle;
        }
    }

    if (value)
        ssa[temp].use_count += uses - remaining - !remaining;
    ssa[id].use_count = remaining;
    if (remaining)
        return false;
    vsir_instruction_make_nop(mov);
    return true;
}

/* A value that is stored in a variable and used as well:
 *
 *     ieq sr9.x, sr8.x, r147.x
 *     mov r273.x, sr9.x
 *     and sr12.x, sr9.x, sr11.x
 *
 * can still be computed into the variable, with the other uses reading that,
 * as long as they come before the variable changes again. Checks that with
 * "apply" false, does it with "apply" true; "def" has by then been changed. */
static bool forward_other_uses(struct vsir_instruction **list, unsigned int count, unsigned int def_index,
        unsigned int mov_index, unsigned int id, unsigned int uses, uint32_t def_mask,
        const struct vsir_dst_operand *dst, uint32_t mov_swizzle, bool apply)
{
    unsigned int inverse[VKD3D_VEC4_SIZE] = {~0u, ~0u, ~0u, ~0u}, first = ~0u, remaining = uses - 1;
    unsigned int temp = dst->reg.idx[0].offset;

    for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
    {
        unsigned int c = vsir_swizzle_get_component(mov_swizzle, j);

        if (!(dst->write_mask & (1u << j)))
            continue;
        if (inverse[c] == ~0u)
            inverse[c] = j;
        if (first == ~0u)
            first = j;
    }

    for (unsigned int k = def_index + 1; k < count && (k < mov_index || k - mov_index <= 64); ++k)
    {
        struct vsir_instruction *ins = list[k];
        bool awkward = false;

        if (k == mov_index)
            continue;
        remaining -= forward_count_uses(ins, id, &awkward);
        if (awkward)
            return false;

        for (unsigned int i = 0; i < ins->src_count; ++i)
        {
            struct vsir_src_operand *src = &ins->src[i];
            enum vsir_data_type data_type = src->reg.data_type;
            uint32_t swizzle = 0;

            if (src->reg.type != VSIR_REGISTER_SSA || src->reg.idx[0].offset != id)
                continue;
            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
            {
                unsigned int c = vsir_swizzle_get_component(src->swizzle, j);

                if (!(def_mask & (1u << c)))
                    vsir_swizzle_set_component(&swizzle, j, first);
                else if (inverse[c] == ~0u)
                    return false;
                else
                    vsir_swizzle_set_component(&swizzle, j, inverse[c]);
            }
            if (apply)
            {
                src->reg = dst->reg;
                src->reg.data_type = data_type;
                src->swizzle = swizzle;
            }
        }

        if (!remaining)
            return true;
        if (k > mov_index && (vsir_opcode_is_block_boundary(ins->opcode) || vsir_instruction_writes_temp(ins, temp)))
            return false;
    }
    return false;
}

'''
s = s[:start] + NEW + s[end:]


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep('''        value = &ssa[ins->src[0].reg.idx[0].offset];
        if (!value->def || value->use_count != 1 || value->def_index >= i || value->def->dst[0].modifiers)
            continue;
''', '''        value = &ssa[ins->src[0].reg.idx[0].offset];
        if (!value->def || !value->use_count || value->def_index >= i || value->def->opcode == VSIR_OP_NOP
                || value->def->dst_count != 1 || value->def->dst[0].modifiers)
            continue;
        if (value->use_count != 1 && (dst->type != VSIR_REGISTER_TEMP || ins->dst[0].modifiers))
            continue;
''')
rep('''        if (forward_destination(value->def, ins) && dst->type == VSIR_REGISTER_SSA)
        {
            ssa[dst->idx[0].offset].def = value->def;
            ssa[dst->idx[0].offset].def_index = value->def_index;
        }
''', '''        if (value->use_count != 1)
        {
            unsigned int id = ins->src[0].reg.idx[0].offset;
            uint32_t def_mask = value->def->dst[0].write_mask, mov_swizzle = ins->src[0].swizzle;
            struct vsir_dst_operand copy = ins->dst[0];

            if (!forward_other_uses(list, count, value->def_index, i, id, value->use_count,
                    def_mask, &copy, mov_swizzle, false) || !forward_destination(value->def, ins))
                continue;
            forward_other_uses(list, count, value->def_index, i, id, value->use_count,
                    def_mask, &copy, mov_swizzle, true);
            ssa[id].use_count = 0;
            continue;
        }

        if (forward_destination(value->def, ins) && dst->type == VSIR_REGISTER_SSA)
        {
            ssa[dst->idx[0].offset].def = value->def;
            ssa[dst->idx[0].offset].def_index = value->def_index;
        }
''')
open(path, "w").write(s)
print("patched")
