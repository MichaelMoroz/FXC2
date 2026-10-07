import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.y")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


# "a - b" is built as "a + (-b)", and -b was computed in b's own type. For a
# float a and an unsigned b that negates the unsigned value first (4294967293
# for 3) and converts afterwards: "at - cell" with a uint2 cell gave numbers
# around minus four billion. Convert b to the type the result will have, then
# negate.
rep('''    return add_expr(ctx, block, op, args, arg->data_type, loc);
}
''', '''    return add_expr(ctx, block, op, args, arg->data_type, loc);
}

/* fxc2: -rhs for "lhs - rhs" and "lhs -= rhs". The negation has to happen in
 * the type the subtraction is done in: an unsigned or boolean rhs under a
 * floating point lhs is converted first. (Between integers it makes no
 * difference: the arithmetic wraps the same either way.) */
static struct hlsl_ir_node *add_negation_for_subtraction(struct hlsl_ctx *ctx, struct hlsl_block *block,
        const struct hlsl_type *lhs_type, struct hlsl_ir_node *rhs, const struct vkd3d_shader_location *loc)
{
    const struct hlsl_type *rhs_type = rhs->data_type;

    if (hlsl_is_numeric_type(lhs_type) && hlsl_is_numeric_type(rhs_type)
            && (lhs_type->e.numeric.type == HLSL_TYPE_FLOAT || lhs_type->e.numeric.type == HLSL_TYPE_HALF
            || lhs_type->e.numeric.type == HLSL_TYPE_DOUBLE)
            && hlsl_type_is_integer(rhs_type))
    {
        struct hlsl_type *type = hlsl_change_base_type(ctx, rhs_type, lhs_type->e.numeric.type);

        if (!(rhs = add_implicit_conversion(ctx, block, rhs, type, loc)))
            return NULL;
    }
    return add_unary_arithmetic_expr(ctx, block, HLSL_OP1_NEG, rhs, loc);
}
''')
rep('''    if (assign_op == ASSIGN_OP_SUB)
    {
        if (!(rhs = add_unary_arithmetic_expr(ctx, block, HLSL_OP1_NEG, rhs, &rhs->loc)))
            return false;
''', '''    if (assign_op == ASSIGN_OP_SUB)
    {
        if (!(rhs = add_negation_for_subtraction(ctx, block, lhs->data_type, rhs, &rhs->loc)))
            return false;
''')
rep('''            if (!(neg = add_unary_arithmetic_expr(ctx, $3, HLSL_OP1_NEG, node_from_block($3), &@2)))
                YYABORT;
            $$ = add_binary_expr_merge(ctx, $1, $3, HLSL_OP2_ADD, &@2);
''', '''            if (!(neg = add_negation_for_subtraction(ctx, $3, node_from_block($1)->data_type, node_from_block($3), &@2)))
                YYABORT;
            $$ = add_binary_expr_merge(ctx, $1, $3, HLSL_OP2_ADD, &@2);
''')
open(p, "w").write(s)
print("patched")
