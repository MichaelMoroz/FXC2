import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:80], s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("hlsl.h", [
    ('''    HLSL_OP2_MUL,
    HLSL_OP2_NEQUAL,
''', '''    HLSL_OP2_MUL,
    /* fxc2: the high 32 bits of the 64-bit product of two 32-bit integers,
     * signed or unsigned as the type is. */
    HLSL_OP2_MUL_HI,
    HLSL_OP2_NEQUAL,
'''),
])
edit("hlsl.c", [
    ('''        [HLSL_OP2_MUL]         = "*",
''', '''        [HLSL_OP2_MUL]         = "*",
        [HLSL_OP2_MUL_HI]      = "mulhi",
'''),
])

INTRINSICS = r'''/* fxc2: what the imul and umul instructions compute and HLSL has no way to
 * ask for, the high half of a 32 x 32 -> 64 bit product:
 *
 *     mulhi(a, b)                     the high half; signed for int, else unsigned
 *     umulExtended(a, b, hi, lo)      both halves, as in GLSL
 *     imulExtended(a, b, hi, lo)
 *
 * Asking for both halves of one product gives one instruction with both
 * destinations. FXC knows none of these; see __FXC2__. */
static struct hlsl_ir_node *add_mul_hi(struct hlsl_ctx *ctx, const struct parse_initializer *params,
        enum hlsl_base_type base, struct hlsl_ir_node **lo, const struct vkd3d_shader_location *loc)
{
    struct hlsl_ir_node *operands[HLSL_MAX_OPERANDS] = {0};
    const struct hlsl_type *arg1 = params->args[0]->data_type, *arg2 = params->args[1]->data_type;
    unsigned int dimx;
    struct hlsl_type *type;

    if (arg1->class > HLSL_CLASS_VECTOR || arg2->class > HLSL_CLASS_VECTOR)
    {
        hlsl_error(ctx, loc, VKD3D_SHADER_ERROR_HLSL_INVALID_TYPE, "Extended multiplication takes scalars or vectors.");
        return NULL;
    }
    if (hlsl_version_lt(ctx, 4, 0))
    {
        hlsl_error(ctx, loc, VKD3D_SHADER_ERROR_HLSL_INCOMPATIBLE_PROFILE,
                "Extended multiplication needs shader model 4 or higher.");
        return NULL;
    }

    if (arg1->class == HLSL_CLASS_SCALAR)
        dimx = arg2->e.numeric.dimx;
    else if (arg2->class == HLSL_CLASS_SCALAR)
        dimx = arg1->e.numeric.dimx;
    else
        dimx = min(arg1->e.numeric.dimx, arg2->e.numeric.dimx);
    type = hlsl_get_vector_type(ctx, base, dimx);

    if (!(operands[0] = add_implicit_conversion(ctx, params->instrs, params->args[0], type, loc))
            || !(operands[1] = add_implicit_conversion(ctx, params->instrs, params->args[1], type, loc)))
        return NULL;
    if (lo && !(*lo = add_expr(ctx, params->instrs, HLSL_OP2_MUL, operands, type, loc)))
        return NULL;
    return add_expr(ctx, params->instrs, HLSL_OP2_MUL_HI, operands, type, loc);
}

static bool intrinsic_mulhi(struct hlsl_ctx *ctx,
        const struct parse_initializer *params, const struct vkd3d_shader_location *loc)
{
    const struct hlsl_type *arg1 = params->args[0]->data_type, *arg2 = params->args[1]->data_type;
    bool is_signed = hlsl_is_numeric_type(arg1) && hlsl_is_numeric_type(arg2)
            && arg1->e.numeric.type == HLSL_TYPE_INT && arg2->e.numeric.type == HLSL_TYPE_INT;

    return !!add_mul_hi(ctx, params, is_signed ? HLSL_TYPE_INT : HLSL_TYPE_UINT, NULL, loc);
}

static bool intrinsic_mul_extended(struct hlsl_ctx *ctx, const struct parse_initializer *params,
        enum hlsl_base_type base, const struct vkd3d_shader_location *loc)
{
    struct hlsl_ir_node *hi, *lo;

    if (!(hi = add_mul_hi(ctx, params, base, &lo, loc)))
        return false;
    if (!add_assignment(ctx, params->instrs, params->args[2], ASSIGN_OP_ASSIGN, hi, false)
            || !add_assignment(ctx, params->instrs, params->args[3], ASSIGN_OP_ASSIGN, lo, false))
        return false;
    add_void_expr(ctx, params->instrs, loc);
    return true;
}

static bool intrinsic_umulExtended(struct hlsl_ctx *ctx,
        const struct parse_initializer *params, const struct vkd3d_shader_location *loc)
{
    return intrinsic_mul_extended(ctx, params, HLSL_TYPE_UINT, loc);
}

static bool intrinsic_imulExtended(struct hlsl_ctx *ctx,
        const struct parse_initializer *params, const struct vkd3d_shader_location *loc)
{
    return intrinsic_mul_extended(ctx, params, HLSL_TYPE_INT, loc);
}

'''

path = base + "hlsl.y"
s = open(path).read()
anchor = '''static bool intrinsic_countbits(struct hlsl_ctx *ctx,
        const struct parse_initializer *params, const struct vkd3d_shader_location *loc)
{'''
assert s.count(anchor) == 1
s = s.replace(anchor, INTRINSICS + anchor)
old = '''    {"isfinite", '''
assert s.count(old) == 1, s.count(old)
idx = s.index(old)
line_end = s.index("\n", idx)
isinf_line = s[idx:line_end]
s = s.replace(isinf_line, '''    {"imulExtended",                        4, true,  intrinsic_imulExtended},
''' + isinf_line, 1)
old = '''    {"mul",                                 2, true,  intrinsic_mul},
'''
assert s.count(old) == 1
s = s.replace(old, old + '''    {"mulhi",                               2, true,  intrinsic_mulhi},
''')
old = '''    {"unpackHalf2x16",'''
if s.count(old) == 1:
    s = s.replace(old, '''    {"umulExtended",                        4, true,  intrinsic_umulExtended},
''' + old)
else:
    # keep the table sorted: before whatever follows "trunc"/"u..." alphabetically
    import re
    m = re.search(r'\n    \{"transpose",[^\n]*\n(    \{"trunc",[^\n]*\n)?', s)
    assert m
    s = s[:m.end()] + '''    {"umulExtended",                        4, true,  intrinsic_umulExtended},
''' + s[m.end():]
open(path, "w").write(s)

edit("hlsl_codegen.c", [
    ('''        case HLSL_OP2_MOD:
            switch (dst_type->e.numeric.type)
            {
                case HLSL_TYPE_MIN16UINT: /* FIXME: Needs minimum-precision annotations. */
                case HLSL_TYPE_UINT:
                    sm4_generate_vsir_expr_with_two_destinations(ctx, program, VSIR_OP_UDIV, expr, 1);
                    return true;
''', '''        case HLSL_OP2_MUL_HI:
            /* fxc2 */
            sm4_generate_vsir_expr_with_two_destinations(ctx, program,
                    dst_type->e.numeric.type == HLSL_TYPE_INT ? VSIR_OP_IMUL : VSIR_OP_UMUL, expr, 0);
            return true;

        case HLSL_OP2_MOD:
            switch (dst_type->e.numeric.type)
            {
                case HLSL_TYPE_MIN16UINT: /* FIXME: Needs minimum-precision annotations. */
                case HLSL_TYPE_UINT:
                    sm4_generate_vsir_expr_with_two_destinations(ctx, program, VSIR_OP_UDIV, expr, 1);
                    return true;
'''),
])

edit("tpf.c", [
    ('''        case VSIR_OP_UDIV:
''', '''        case VSIR_OP_UDIV:
        case VSIR_OP_UMUL:
'''),
])

MERGE = r'''static bool forward_same_source(const struct vsir_src_operand *a, const struct vsir_src_operand *b)
{
    if (a->reg.type != b->reg.type || a->modifiers || b->modifiers || a->reg.dimension != b->reg.dimension)
        return false;
    if (a->reg.type == VSIR_REGISTER_IMMCONST)
        return !memcmp(a->reg.u.immconst_u32, b->reg.u.immconst_u32, sizeof(a->reg.u.immconst_u32));
    return a->reg.type == VSIR_REGISTER_SSA && a->reg.idx[0].offset == b->reg.idx[0].offset
            && a->swizzle == b->swizzle;
}

/* fxc2: imul and umul have two destinations, the high and the low half of
 * the product. The two halves of one product come out of the HLSL compiler as
 * two instructions with one destination each; make them one. (The low halves
 * of the signed and of the unsigned product are the same.) */
static void vsir_program_merge_multiplies(struct vsir_instruction **list, unsigned int count,
        struct forward_ssa *ssa)
{
    for (unsigned int i = 0; i < count; ++i)
    {
        struct vsir_instruction *a = list[i], *b;
        unsigned int have, want, j;

        if ((a->opcode != VSIR_OP_IMUL && a->opcode != VSIR_OP_UMUL) || a->dst_count != 2 || a->src_count != 2)
            continue;
        if ((a->dst[0].reg.type == VSIR_REGISTER_NULL) == (a->dst[1].reg.type == VSIR_REGISTER_NULL))
            continue;
        have = a->dst[0].reg.type == VSIR_REGISTER_NULL;
        want = !have;
        if (a->dst[have].reg.type != VSIR_REGISTER_SSA)
            continue;

        for (j = i + 1; j < count && j - i <= 16; ++j)
        {
            b = list[j];
            if (vsir_opcode_is_block_boundary(b->opcode))
                break;
            if ((b->opcode != VSIR_OP_IMUL && b->opcode != VSIR_OP_UMUL) || b->dst_count != 2 || b->src_count != 2
                    || b->dst[want].reg.type != VSIR_REGISTER_SSA || b->dst[have].reg.type != VSIR_REGISTER_NULL
                    || b->dst[want].write_mask != a->dst[have].write_mask
                    || b->dst[want].modifiers || a->dst[have].modifiers)
                continue;
            if (!((forward_same_source(&a->src[0], &b->src[0]) && forward_same_source(&a->src[1], &b->src[1]))
                    || (forward_same_source(&a->src[0], &b->src[1]) && forward_same_source(&a->src[1], &b->src[0]))))
                continue;

            /* The one that computes the high half says which product it is. */
            if (want == 0)
                a->opcode = b->opcode;
            a->dst[want] = b->dst[want];
            ssa[a->dst[want].reg.idx[0].offset].def = a;
            ssa[a->dst[want].reg.idx[0].offset].def_index = i;
            vsir_instruction_make_nop(b);
            break;
        }
    }
}

'''

path = base + "ir.c"
s = open(path).read()
anchor = "static enum vkd3d_result vsir_program_forward_destinations(struct vsir_program *program)\n{"
assert s.count(anchor) == 1
s = s.replace(anchor, MERGE + anchor)
old = '''    for (unsigned int i = 0; i < count; ++i)
    {
        ins = list[i];
        if (ins->opcode == VSIR_OP_MOV && ins->dst_count == 1 && ins->src_count == 1
                && ins->dst[0].reg.type == VSIR_REGISTER_SSA && !ins->dst[0].modifiers
'''
assert s.count(old) == 1
s = s.replace(old, '''    vsir_program_merge_multiplies(list, count, ssa);

''' + old)
open(path, "w").write(s)
print("patched")
