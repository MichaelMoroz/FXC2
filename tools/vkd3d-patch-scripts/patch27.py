import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep('''    /* fxc2: speculatively unrolling every loop, as upstream does to mimic
     * FXC, makes compile time and code size explode on loop-heavy SM4+
     * shaders. Only unroll loops marked [unroll], unless the
     * VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT environment variable sets a limit. */
    if (loop->unroll_type != HLSL_LOOP_FORCE_UNROLL && hlsl_version_ge(ctx, 4, 0))
    {
        const char *limit = getenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT");

        if (!limit || !(unroll_limit = strtoul(limit, NULL, 0)))
        {
            loop->unroll_type = HLSL_LOOP_FORCE_LOOP;
            return false;
        }
    }
''', '''    /* fxc2: speculatively unrolling every loop up to 254 iterations, as
     * upstream does to mimic FXC, makes compile time and code size explode on
     * loop-heavy SM4+ shaders: the unroller does not know the trip count, it
     * just copies the body until the copies stop being reachable. On the
     * other hand "for (i = 0; i < 6; ++i) a[i] = ..." is much better off
     * unrolled: no loop, and the array stays in registers. So give each loop
     * a budget of instructions and try only as many iterations as fit in it,
     * which leaves big bodies alone entirely. Loops marked [unroll] are
     * unrolled as asked. VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT forces an iteration
     * limit, VKD3D_HLSL_UNROLL_BUDGET sets the budget (0: never). */
    if (loop->unroll_type != HLSL_LOOP_FORCE_UNROLL && hlsl_version_ge(ctx, 4, 0))
    {
        const char *limit = getenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT");
        const char *budget_env = getenv("VKD3D_HLSL_UNROLL_BUDGET");
        unsigned int budget = budget_env ? strtoul(budget_env, NULL, 0) : 400;
        unsigned int size;

        if (limit)
        {
            unroll_limit = strtoul(limit, NULL, 0);
        }
        else if (budget && loop_looks_countable(loop))
        {
            size = max(unroll_block_size(&loop->body) + unroll_block_size(&loop->iter), 1);
            unroll_limit = min(budget / size, 64);
            if (unroll_limit < 2)
                unroll_limit = 0;
        }

        if (!unroll_limit)
        {
            loop->unroll_type = HLSL_LOOP_FORCE_LOOP;
            return false;
        }
    }
''')

rep('''static bool unroll_loops(struct hlsl_ctx *ctx, struct hlsl_ir_node *node, void *context)
{''', '''/* fxc2: instructions in a block, nested blocks included. */
static unsigned int unroll_block_size(const struct hlsl_block *block)
{
    const struct hlsl_ir_node *instr;
    unsigned int size = 0;

    LIST_FOR_EACH_ENTRY(instr, &block->instrs, struct hlsl_ir_node, entry)
    {
        if (instr->type != HLSL_IR_CONSTANT)
            ++size;
        if (instr->type == HLSL_IR_IF)
        {
            size += unroll_block_size(&hlsl_ir_if(instr)->then_block);
            size += unroll_block_size(&hlsl_ir_if(instr)->else_block);
        }
        else if (instr->type == HLSL_IR_LOOP)
        {
            size += unroll_block_size(&hlsl_ir_loop(instr)->body);
            size += unroll_block_size(&hlsl_ir_loop(instr)->iter);
        }
        else if (instr->type == HLSL_IR_SWITCH)
        {
            const struct hlsl_ir_switch_case *c;

            LIST_FOR_EACH_ENTRY(c, &hlsl_ir_switch(instr)->cases, struct hlsl_ir_switch_case, entry)
                size += unroll_block_size(&c->body);
        }
    }
    return size;
}

/* fxc2: an attempt to unroll costs a pass over everything before the loop,
 * so only try loops whose condition compares local variables with
 * constants ("i < 6"), not ones bounded by uniforms or by data. */
static bool loop_condition_is_countable(const struct hlsl_ir_node *node, unsigned int depth, bool *has_constant)
{
    unsigned int i;

    if (node->type == HLSL_IR_CONSTANT)
    {
        *has_constant = true;
        return true;
    }
    if (node->type == HLSL_IR_LOAD)
    {
        const struct hlsl_ir_var *var = hlsl_ir_load(node)->src.var;

        return !var->is_uniform && !var->is_input_semantic && !var->is_tgsm
                && node->data_type->class <= HLSL_CLASS_VECTOR;
    }
    if (node->type == HLSL_IR_SWIZZLE)
        return depth < 6 && loop_condition_is_countable(hlsl_ir_swizzle(node)->val.node, depth + 1, has_constant);
    if (node->type != HLSL_IR_EXPR || depth >= 6)
        return false;
    for (i = 0; i < HLSL_MAX_OPERANDS && hlsl_ir_expr(node)->operands[i].node; ++i)
    {
        if (!loop_condition_is_countable(hlsl_ir_expr(node)->operands[i].node, depth + 1, has_constant))
            return false;
    }
    return true;
}

static bool loop_looks_countable(const struct hlsl_ir_loop *loop)
{
    const struct hlsl_ir_node *instr;
    bool has_constant = false;

    LIST_FOR_EACH_ENTRY(instr, &loop->body.instrs, struct hlsl_ir_node, entry)
    {
        if (instr->type == HLSL_IR_IF && hlsl_ir_if(instr)->is_loop_conditional)
            return loop_condition_is_countable(hlsl_ir_if(instr)->condition.node, 0, &has_constant)
                    && has_constant;
    }
    return false;
}

static bool unroll_loops(struct hlsl_ctx *ctx, struct hlsl_ir_node *node, void *context)
{''')
rep('''    if (!loop_unrolling_unroll_loop(ctx, program, loop, unroll_limit, false))
        loop->unroll_type = HLSL_LOOP_FORCE_LOOP;

    return true;
''', '''    if (!loop_unrolling_unroll_loop(ctx, program, loop, unroll_limit, false))
    {
        /* fxc2: nothing changed, so there is no need to fold the whole
         * program again before looking at the next loop. */
        loop->unroll_type = HLSL_LOOP_FORCE_LOOP;
        return false;
    }

    return true;
''')
rep('''    for (;;)
    {
        hlsl_run_folding_passes(ctx, block);
        if (!hlsl_transform_ir_once(ctx, unroll_loops, block, block))
            break;
    }
''', '''    for (;;)
    {
        hlsl_run_folding_passes(ctx, block);
        /* fxc2: upstream folds the whole program again after every single
         * loop it unrolls, which is most of the compile time once more than
         * a few loops qualify. One loop per nesting level and round is as
         * good: each attempt propagates constants up to its loop by itself. */
        if (hlsl_version_ge(ctx, 4, 0) ? !hlsl_transform_ir(ctx, unroll_loops, block, block)
                : !hlsl_transform_ir_once(ctx, unroll_loops, block, block))
            break;
    }
''')
rep('''    if (!unroll_limit && i == max_iterations)
    {''', '''    /* fxc2: a limit that did not come from an [unroll(n)] in the source is
     * only how far we were willing to try; running into it must leave the
     * loop alone, not cut it short. */
    if ((!unroll_limit || !loop->unroll_limit.node) && i == max_iterations)
    {''')
open(path, "w").write(s)
print("patched")
