import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep('''static bool hlsl_tuning_enabled(const char *variable, bool default_value);

/* Remove HLSL_IR_JUMP_RETURN calls by altering subsequent control flow. */''',
    '''static bool hlsl_tuning_enabled(const char *variable, bool default_value);

/* fxc2: number of instructions in a block, nested ones included, up to a
 * limit: for deciding whether code is small enough to be duplicated. */
static unsigned int block_size_up_to(const struct hlsl_block *block, unsigned int limit)
{
    const struct hlsl_ir_node *instr;
    unsigned int size = 0;

    LIST_FOR_EACH_ENTRY(instr, &block->instrs, struct hlsl_ir_node, entry)
    {
        if (instr->type != HLSL_IR_CONSTANT)
            ++size;
        if (instr->type == HLSL_IR_IF)
        {
            size += block_size_up_to(&hlsl_ir_if(instr)->then_block, limit);
            size += block_size_up_to(&hlsl_ir_if(instr)->else_block, limit);
        }
        else if (instr->type == HLSL_IR_LOOP || instr->type == HLSL_IR_SWITCH)
        {
            /* Not worth duplicating. */
            return limit + 1;
        }
        if (size > limit)
            return size;
    }
    return size;
}

static unsigned int return_duplication_limit(void)
{
    static int limit = -1;

    if (limit < 0)
    {
        const char *env = getenv("VKD3D_HLSL_RETURN_DUP");

        limit = env ? atoi(env) : 24;
    }
    return limit;
}

/* Remove HLSL_IR_JUMP_RETURN calls by altering subsequent control flow. */''')

rep('''                if (block_always_returns(&iff->then_block) && !block_contains_return(&iff->else_block))
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
''', '''                bool then_returns = block_contains_return(&iff->then_block);
                bool else_returns = block_contains_return(&iff->else_block);
                struct hlsl_block rest, copy;

                hlsl_block_init(&rest);
                if (block_always_returns(&iff->then_block))
                    continuation = &iff->else_block;
                else if (block_always_returns(&iff->else_block))
                    continuation = &iff->then_block;

                if (continuation)
                {
                    list_move_slice_tail(&rest.instrs, list_next(&block->instrs, &instr->entry),
                            list_tail(&block->instrs));
                    hlsl_block_add_block(continuation, &rest);
                    /* The if is now the last instruction of this block. */
                    next = LIST_ENTRY(&block->instrs, struct hlsl_ir_node, entry);
                }
                else if (then_returns || else_returns)
                {
                    /* Either side may or may not return. When what follows
                     * is small, put a copy on each side, where the returns
                     * inside can be dealt with the same way, rather than
                     * test a flag afterwards. */
                    list_move_slice_tail(&rest.instrs, list_next(&block->instrs, &instr->entry),
                            list_tail(&block->instrs));
                    if (block_size_up_to(&rest, return_duplication_limit()) <= return_duplication_limit()
                            && hlsl_clone_block(ctx, &copy, &rest))
                    {
                        hlsl_block_add_block(&iff->then_block, &copy);
                        hlsl_block_add_block(&iff->else_block, &rest);
                        next = LIST_ENTRY(&block->instrs, struct hlsl_ir_node, entry);
                    }
                    else
                    {
                        /* Too big: put it back. */
                        hlsl_block_add_block(block, &rest);
                        next = LIST_ENTRY(list_next(&block->instrs, &instr->entry), struct hlsl_ir_node, entry);
                    }
                }
            }
''')
open(path, "w").write(s)
print("patched")
