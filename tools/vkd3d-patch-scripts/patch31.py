import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep('''static bool mark_indexable_var(struct hlsl_ctx *ctx, struct hlsl_deref *deref,
        struct hlsl_ir_node *instr)
{''', '''/* fxc2: a * b + c as one mad instruction, when the product is not needed for
 * anything else. FXC does this throughout; it is not done under
 * D3DCOMPILE_IEEE_STRICTNESS, since a driver may evaluate mad as a fused
 * multiply-add. */
static struct hlsl_ir_node *fuse_multiply_add(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr,
        struct hlsl_block *block)
{
    struct hlsl_ir_node *operands[HLSL_MAX_OPERANDS] = {0};
    const struct hlsl_type *type = instr->data_type;
    struct hlsl_ir_expr *expr, *mul;
    unsigned int i;

    if (instr->type != HLSL_IR_EXPR || type->class > HLSL_CLASS_VECTOR)
        return NULL;
    if (type->e.numeric.type != HLSL_TYPE_FLOAT && type->e.numeric.type != HLSL_TYPE_HALF)
        return NULL;
    expr = hlsl_ir_expr(instr);
    if (expr->op != HLSL_OP2_ADD)
        return NULL;

    for (i = 0; i < 2; ++i)
    {
        struct hlsl_ir_node *product = expr->operands[i].node;

        if (product->type != HLSL_IR_EXPR || hlsl_ir_expr(product)->op != HLSL_OP2_MUL
                || list_count(&product->uses) != 1 || !hlsl_types_are_equal(product->data_type, type))
            continue;
        mul = hlsl_ir_expr(product);
        operands[0] = mul->operands[0].node;
        operands[1] = mul->operands[1].node;
        operands[2] = expr->operands[!i].node;
        return hlsl_block_add_expr(ctx, block, HLSL_OP3_MAD, operands, instr->data_type, &instr->loc);
    }
    return NULL;
}

static bool mark_indexable_var(struct hlsl_ctx *ctx, struct hlsl_deref *deref,
        struct hlsl_ir_node *instr)
{''')

rep('''    if (hlsl_version_ge(ctx, 4, 0) && hlsl_tuning_enabled("VKD3D_HLSL_VALUE_NUMBERING", true)
            && lvn_execute(ctx, body))
        hlsl_run_folding_passes(ctx, body);
''', '''    if (hlsl_version_ge(ctx, 4, 0) && hlsl_tuning_enabled("VKD3D_HLSL_VALUE_NUMBERING", true)
            && lvn_execute(ctx, body))
        hlsl_run_folding_passes(ctx, body);
    if (hlsl_version_ge(ctx, 4, 0) && !ctx->compile_info.enforce_ieee_754_fp
            && hlsl_tuning_enabled("VKD3D_HLSL_MAD", true))
        replace_ir(ctx, fuse_multiply_add, body);
''')
open(path, "w").write(s)
print("patched")
