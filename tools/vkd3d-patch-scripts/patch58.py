import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


rep('''        mul = hlsl_ir_expr(product);
        operands[0] = mul->operands[0].node;
        operands[1] = mul->operands[1].node;
        operands[2] = expr->operands[!i].node;
        return hlsl_block_add_expr(ctx, block, HLSL_OP3_MAD, operands, instr->data_type, &instr->loc);
    }
    return NULL;
}''', '''        mul = hlsl_ir_expr(product);
        operands[0] = mul->operands[0].node;
        operands[1] = mul->operands[1].node;
        operands[2] = expr->operands[!i].node;
        return hlsl_block_add_expr(ctx, block, HLSL_OP3_MAD, operands, instr->data_type, &instr->loc);
    }

    /* c - a * b is mad(-a, b, c): the negation is an operand modifier in the
     * bytecode and costs nothing, and FXC writes it so. */
    for (i = 0; i < 2; ++i)
    {
        struct hlsl_ir_node *neg = expr->operands[i].node, *product;

        if (neg->type != HLSL_IR_EXPR || hlsl_ir_expr(neg)->op != HLSL_OP1_NEG || list_count(&neg->uses) != 1)
            continue;
        product = hlsl_ir_expr(neg)->operands[0].node;
        if (product->type != HLSL_IR_EXPR || hlsl_ir_expr(product)->op != HLSL_OP2_MUL
                || list_count(&product->uses) != 1 || !hlsl_types_are_equal(product->data_type, type))
            continue;
        mul = hlsl_ir_expr(product);
        operands[0] = hlsl_block_add_unary_expr(ctx, block, HLSL_OP1_NEG, mul->operands[0].node, &instr->loc);
        operands[1] = mul->operands[1].node;
        operands[2] = expr->operands[!i].node;
        return hlsl_block_add_expr(ctx, block, HLSL_OP3_MAD, operands, instr->data_type, &instr->loc);
    }
    return NULL;
}''')
open(p, "w").write(s)
print("patched")
