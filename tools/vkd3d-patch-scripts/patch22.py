import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep('''/* Remove HLSL_IR_JUMP_RETURN calls by altering subsequent control flow. */
static bool lower_return(struct hlsl_ctx *ctx, struct hlsl_ir_function_decl *func,
        struct hlsl_block *block, bool in_loop)
{''', '''/* fxc2: whether a block contains a return at all, and whether every path
 * through it ends in one. Used by lower_return() to turn
 *     if (c) return x;  rest;
 * into
 *     if (c) x; else rest;
 * instead of guarding "rest" with a second test of a "has returned" flag:
 * one branch fewer on the path, and no values to merge after the first if. */
static bool block_contains_return(const struct hlsl_block *block)
{
    const struct hlsl_ir_node *instr;

    LIST_FOR_EACH_ENTRY(instr, &block->instrs, struct hlsl_ir_node, entry)
    {
        if (instr->type == HLSL_IR_JUMP && hlsl_ir_jump(instr)->type == HLSL_IR_JUMP_RETURN)
            return true;
        if (instr->type == HLSL_IR_IF && (block_contains_return(&hlsl_ir_if(instr)->then_block)
                || block_contains_return(&hlsl_ir_if(instr)->else_block)))
            return true;
        if (instr->type == HLSL_IR_LOOP && (block_contains_return(&hlsl_ir_loop(instr)->body)
                || block_contains_return(&hlsl_ir_loop(instr)->iter)))
            return true;
        if (instr->type == HLSL_IR_SWITCH)
        {
            const struct hlsl_ir_switch_case *c;

            LIST_FOR_EACH_ENTRY(c, &hlsl_ir_switch(instr)->cases, struct hlsl_ir_switch_case, entry)
            {
                if (block_contains_return(&c->body))
                    return true;
            }
        }
    }
    return false;
}

static bool block_always_returns(const struct hlsl_block *block)
{
    const struct hlsl_ir_node *instr;

    LIST_FOR_EACH_ENTRY(instr, &block->instrs, struct hlsl_ir_node, entry)
    {
        if (instr->type == HLSL_IR_JUMP)
            return hlsl_ir_jump(instr)->type == HLSL_IR_JUMP_RETURN;
        if (instr->type == HLSL_IR_IF && block_always_returns(&hlsl_ir_if(instr)->then_block)
                && block_always_returns(&hlsl_ir_if(instr)->else_block))
            return true;
    }
    return false;
}

static bool hlsl_tuning_enabled(const char *variable, bool default_value);

/* Remove HLSL_IR_JUMP_RETURN calls by altering subsequent control flow. */
static bool lower_return(struct hlsl_ctx *ctx, struct hlsl_ir_function_decl *func,
        struct hlsl_block *block, bool in_loop)
{''')

rep('''        else if (instr->type == HLSL_IR_IF)
        {
            struct hlsl_ir_if *iff = hlsl_ir_if(instr);

            has_early_return |= lower_return(ctx, func, &iff->then_block, in_loop);
            has_early_return |= lower_return(ctx, func, &iff->else_block, in_loop);
''', '''        else if (instr->type == HLSL_IR_IF)
        {
            struct hlsl_ir_if *iff = hlsl_ir_if(instr);
            struct hlsl_block *continuation = NULL;

            /* fxc2: when one side always returns and the other never does,
             * what follows the if can only be reached through the other
             * side, so it belongs there. */
            if (!in_loop && &instr->entry != list_tail(&block->instrs)
                    && hlsl_tuning_enabled("VKD3D_HLSL_RETURN_ELSE", true))
            {
                if (block_always_returns(&iff->then_block) && !block_contains_return(&iff->else_block))
                    continuation = &iff->else_block;
                else if (block_always_returns(&iff->else_block) && !block_contains_return(&iff->then_block))
                    continuation = &iff->then_block;
            }
            if (continuation)
            {
                struct hlsl_block rest;

                hlsl_block_init(&rest);
                list_move_slice_tail(&rest.instrs, list_next(&block->instrs, &instr->entry),
                        list_tail(&block->instrs));
                hlsl_block_add_block(continuation, &rest);
                /* The if is now the last instruction of this block. */
                next = LIST_ENTRY(&block->instrs, struct hlsl_ir_node, entry);
            }

            has_early_return |= lower_return(ctx, func, &iff->then_block, in_loop);
            has_early_return |= lower_return(ctx, func, &iff->else_block, in_loop);
'''),
open(path, "w").write(s)
print("patched")
