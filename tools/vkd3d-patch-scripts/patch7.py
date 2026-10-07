import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (old, s.count(old))
    s = s.replace(old, new)


rep('''static struct hlsl_ir_node *evaluate_conditionals_recurse(struct hlsl_ctx *ctx,
        struct hlsl_block *block, const struct hlsl_ir_node *cond, bool cond_value,
        struct hlsl_ir_node *instr, const struct vkd3d_shader_location *loc)
{''', '''/* fxc2: this walks the operands as a tree, but they form a graph with shared
 * subexpressions, so the cost is exponential in its depth. Unrolled loops
 * produce long chains of selects where that meant minutes per shader. It is
 * only an optimisation, so stop looking beyond a few levels. */
#define EVALUATE_CONDITIONALS_MAX_DEPTH 6

static struct hlsl_ir_node *evaluate_conditionals_recurse(struct hlsl_ctx *ctx,
        struct hlsl_block *block, const struct hlsl_ir_node *cond, bool cond_value,
        struct hlsl_ir_node *instr, const struct vkd3d_shader_location *loc, unsigned int depth)
{''')
rep('''    if (instr->type != HLSL_IR_EXPR)
        return NULL;
    expr = hlsl_ir_expr(instr);

    if (expr->op == HLSL_OP3_TERNARY && nodes_are_equivalent(cond, expr->operands[0].node))''',
    '''    if (instr->type != HLSL_IR_EXPR || depth > EVALUATE_CONDITIONALS_MAX_DEPTH)
        return NULL;
    expr = hlsl_ir_expr(instr);

    if (expr->op == HLSL_OP3_TERNARY && nodes_are_equivalent(cond, expr->operands[0].node))''')
rep("res = evaluate_conditionals_recurse(ctx, block, cond, cond_value, x, loc);",
    "res = evaluate_conditionals_recurse(ctx, block, cond, cond_value, x, loc, depth + 1);")
rep("operands[i] = evaluate_conditionals_recurse(ctx, block, cond, cond_value, expr->operands[i].node, loc);",
    "operands[i] = evaluate_conditionals_recurse(ctx, block, cond, cond_value,\n                expr->operands[i].node, loc, depth + 1);")
rep("res_x = evaluate_conditionals_recurse(ctx, block, c, true, x, &instr->loc);",
    "res_x = evaluate_conditionals_recurse(ctx, block, c, true, x, &instr->loc, 0);")
rep("res_y = evaluate_conditionals_recurse(ctx, block, c, false, y, &instr->loc);",
    "res_y = evaluate_conditionals_recurse(ctx, block, c, false, y, &instr->loc, 0);")
open(path, "w").write(s)
print("patched")
