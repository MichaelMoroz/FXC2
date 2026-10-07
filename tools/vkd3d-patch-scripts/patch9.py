import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old, s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("hlsl.y", [
    ('''statement:
      declaration_statement
    | expr_statement
''', '''statement:
      declaration_statement
    | expr_statement
    /* fxc2: FXC accepts and ignores attributes such as [branch] in front of
     * statements they mean nothing for. */
    | attribute_list declaration_statement
        {
            cleanup_parse_attribute_list(&$1);
            $$ = $2;
        }
    | attribute_list expr_statement
        {
            cleanup_parse_attribute_list(&$1);
            $$ = $2;
        }
'''),
])

edit("hlsl_codegen.c", [
    ('''static bool normalize_switch_cases(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{''', '''/* fxc2: a case may also end in an if whose branches both leave it, as in
 * "case 1: if (x) return a; else break;". */
static bool block_ends_with_break(const struct hlsl_block *block)
{
    const struct hlsl_ir_node *node;

    if (list_empty(&block->instrs))
        return false;
    node = LIST_ENTRY(list_tail(&block->instrs), struct hlsl_ir_node, entry);
    if (node->type == HLSL_IR_JUMP)
        return hlsl_ir_jump(node)->type == HLSL_IR_JUMP_BREAK;
    if (node->type == HLSL_IR_IF)
    {
        const struct hlsl_ir_if *iff = hlsl_ir_if(node);

        return block_ends_with_break(&iff->then_block) && block_ends_with_break(&iff->else_block);
    }
    return false;
}

static bool normalize_switch_cases(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{'''),
    ('''            node = LIST_ENTRY(list_tail(&c->body.instrs), struct hlsl_ir_node, entry);
            if (node->type == HLSL_IR_JUMP)
                terminal_break = (hlsl_ir_jump(node)->type == HLSL_IR_JUMP_BREAK);
''', '''            node = LIST_ENTRY(list_tail(&c->body.instrs), struct hlsl_ir_node, entry);
            if (node->type == HLSL_IR_JUMP)
                terminal_break = (hlsl_ir_jump(node)->type == HLSL_IR_JUMP_BREAK);
            else if (block_ends_with_break(&c->body))
            {
                /* Give the block the shape the rest of the compiler expects. */
                hlsl_block_add_jump(ctx, &c->body, HLSL_IR_JUMP_BREAK, NULL, &c->loc);
                terminal_break = true;
            }
'''),
])
print("patched")
