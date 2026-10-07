import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.y")
s = open(path).read()
old = '''    struct hlsl_ir_node *args[HLSL_MAX_OPERANDS] = {arg};

    if (arg->data_type->class == HLSL_CLASS_ERROR)
        return arg;

    return add_expr(ctx, block, op, args, arg->data_type, loc);
'''
new = '''    struct hlsl_ir_node *args[HLSL_MAX_OPERANDS] = {arg};

    if (arg->data_type->class == HLSL_CLASS_ERROR)
        return arg;

    /* fxc2: negating a bool yields an int, as in "x - (a > b)". Subtraction
     * is built as an addition of the negated operand, so without this the
     * negation would be done on the bool itself, which has no meaning. */
    if (op == HLSL_OP1_NEG && hlsl_is_numeric_type(arg->data_type)
            && arg->data_type->e.numeric.type == HLSL_TYPE_BOOL)
    {
        struct hlsl_type *int_type = hlsl_change_base_type(ctx, arg->data_type, HLSL_TYPE_INT);

        if (!(arg = add_implicit_conversion(ctx, block, arg, int_type, loc)))
            return NULL;
        args[0] = arg;
    }

    return add_expr(ctx, block, op, args, arg->data_type, loc);
'''
assert s.count(old) == 1
open(path, "w").write(s.replace(old, new))
print("patched")
