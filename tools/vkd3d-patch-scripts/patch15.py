import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_constant_ops.c")
s = open(path).read()
old = '''    switch (expr->op)
    {
        case HLSL_OP2_ADD:
            if (hlsl_constant_is_zero(const_arg))
                return mut_arg;
            break;
'''
new = '''    /* fxc2: strength reduction. Integer division is slow on a GPU, and FXC
     * never leaves a multiplication or an unsigned division by a power of
     * two in its output either. */
    if (hlsl_type_is_integer(instr->data_type) && instr->data_type->e.numeric.type != HLSL_TYPE_BOOL
            && (expr->op == HLSL_OP2_MUL || expr->op == HLSL_OP2_DIV || expr->op == HLSL_OP2_MOD)
            && !hlsl_constant_is_one(const_arg))
    {
        unsigned int dimx = const_arg->node.data_type->e.numeric.dimx, k;
        bool const_is_rhs = &const_arg->node == expr->operands[1].node;
        struct hlsl_constant_value shifts = {0}, masks = {0};
        bool pow2 = true;

        for (k = 0; k < dimx; ++k)
        {
            uint32_t v = const_arg->value.u[k].u;

            if (!v || (v & (v - 1)))
                pow2 = false;
            else
                shifts.u[k].u = vkd3d_log2i(v);
            masks.u[k].u = v - 1;
        }

        if (pow2 && expr->op == HLSL_OP2_MUL)
        {
            struct hlsl_ir_node *c = hlsl_block_add_constant(ctx, block,
                    const_arg->node.data_type, &shifts, &instr->loc);

            return hlsl_block_add_binary_expr(ctx, block, HLSL_OP2_LSHIFT, mut_arg, c);
        }
        if (pow2 && const_is_rhs && hlsl_type_is_unsigned_integer(instr->data_type)
                && hlsl_type_is_unsigned_integer(mut_arg->data_type))
        {
            struct hlsl_ir_node *c = hlsl_block_add_constant(ctx, block, const_arg->node.data_type,
                    expr->op == HLSL_OP2_DIV ? &shifts : &masks, &instr->loc);

            return hlsl_block_add_binary_expr(ctx, block,
                    expr->op == HLSL_OP2_DIV ? HLSL_OP2_RSHIFT : HLSL_OP2_BIT_AND, mut_arg, c);
        }
    }

    switch (expr->op)
    {
        case HLSL_OP2_ADD:
            if (hlsl_constant_is_zero(const_arg))
                return mut_arg;
            break;
'''
assert s.count(old) == 1
open(path, "w").write(s.replace(old, new))
print("patched")
