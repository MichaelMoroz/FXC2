import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:80], s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("ir.c", [
    # A swizzle of a value is emitted as a mov as well; that one can be read
    # through wherever the value is used.
    ('''static bool forward_source(struct vsir_instruction **list, unsigned int count, unsigned int index,
        const struct forward_ssa *ssa)
{
    struct vsir_instruction *mov = list[index];
    unsigned int id = mov->dst[0].reg.idx[0].offset, temp = mov->src[0].reg.idx[0].offset;
    unsigned int remaining = ssa[id].use_count, end;

    if (!remaining)
        return false;

    for (end = index + 1; end < count && end - index <= 64; ++end)
    {
        const struct vsir_instruction *ins = list[end];

        if (vsir_opcode_is_block_boundary(ins->opcode))
            return false;
''', '''static bool forward_source(struct vsir_instruction **list, unsigned int count, unsigned int index,
        struct forward_ssa *ssa)
{
    struct vsir_instruction *mov = list[index];
    unsigned int id = mov->dst[0].reg.idx[0].offset, temp = mov->src[0].reg.idx[0].offset;
    /* A copy of a value, "mov sr2.x, sr1.wxxx", is how a swizzle comes out.
     * A value never changes, so that one holds wherever it is used. */
    bool value = mov->src[0].reg.type == VSIR_REGISTER_SSA;
    unsigned int remaining = ssa[id].use_count, uses = remaining, end, first = 0;

    if (!remaining)
        return false;
    while (!(mov->dst[0].write_mask & (1u << first)))
        ++first;

    for (end = index + 1; end < count && (value || end - index <= 64); ++end)
    {
        const struct vsir_instruction *ins = list[end];

        if (!value && vsir_opcode_is_block_boundary(ins->opcode))
            return false;
'''),
    ('''            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
            {
                /* Components the copy does not have may be named where they
                 * are not used; all the same, leave those alone. */
                if (!(mov->dst[0].write_mask & (1u << vsir_swizzle_get_component(src->swizzle, j))))
                    return false;
            }
            --remaining;
''', '''            --remaining;
'''),
    ('''        if (!remaining)
            break;
        if (vsir_instruction_writes_temp(ins, temp))
            return false;
''', '''        if (!remaining)
            break;
        if (!value && vsir_instruction_writes_temp(ins, temp))
            return false;
'''),
    ('''            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
                vsir_swizzle_set_component(&swizzle, j, vsir_swizzle_get_component(mov->src[0].swizzle,
                        vsir_swizzle_get_component(src->swizzle, j)));
            src->reg = mov->src[0].reg;
''', '''            for (unsigned int j = 0; j < VKD3D_VEC4_SIZE; ++j)
            {
                unsigned int component = vsir_swizzle_get_component(src->swizzle, j);

                /* Components the copy does not have can be named where they
                 * are not used. */
                if (!(mov->dst[0].write_mask & (1u << component)))
                    component = first;
                vsir_swizzle_set_component(&swizzle, j, vsir_swizzle_get_component(mov->src[0].swizzle, component));
            }
            src->reg = mov->src[0].reg;
'''),
    ('''    vsir_instruction_make_nop(mov);
    return true;
}

static bool vsir_opcode_is_conditional''', '''    if (value)
        ssa[temp].use_count += uses - 1;
    vsir_instruction_make_nop(mov);
    return true;
}

static bool vsir_opcode_is_conditional'''),
    ('''                && ins->src[0].reg.type == VSIR_REGISTER_TEMP && !ins->src[0].modifiers
                && ins->src[0].reg.idx_count == 1 && !ins->src[0].reg.idx[0].rel_addr
                && ins->src[0].reg.dimension == VSIR_DIMENSION_VEC4
                && ssa[ins->dst[0].reg.idx[0].offset].def == ins)
            forward_source(list, count, i, ssa);''', '''                && (ins->src[0].reg.type == VSIR_REGISTER_TEMP || ins->src[0].reg.type == VSIR_REGISTER_SSA)
                && !ins->src[0].modifiers
                && ins->src[0].reg.idx_count == 1 && !ins->src[0].reg.idx[0].rel_addr
                && ins->src[0].reg.dimension == VSIR_DIMENSION_VEC4
                && ssa[ins->dst[0].reg.idx[0].offset].def == ins)
            forward_source(list, count, i, ssa);'''),

    # "not" of a variable right in front of the test.
    ('''                && def->dst[0].reg.idx[0].offset == src->reg.idx[0].offset && !def->dst[0].modifiers
                && def->src[0].reg.type == VSIR_REGISTER_SSA && !def->src[0].modifiers
''', '''                && def->dst[0].reg.idx[0].offset == src->reg.idx[0].offset && !def->dst[0].modifiers
                && !def->src[0].modifiers && def->src[0].reg.dimension == VSIR_DIMENSION_VEC4
                && (def->src[0].reg.type == VSIR_REGISTER_SSA
                /* A variable must not change in between; take it when the two are adjacent. */
                || (def->src[0].reg.type == VSIR_REGISTER_TEMP && def->src[0].reg.idx_count == 1
                && !def->src[0].reg.idx[0].rel_addr
                && forward_skip_nops(list, count, ssa[src->reg.idx[0].offset].def_index + 1) == i))
'''),
])
print("patched")
