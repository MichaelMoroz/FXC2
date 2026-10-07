import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new, *count in pairs:
        n = count[0] if count else 1
        assert s.count(old) == n, (name, old, s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("hlsl.h", [
    ('''struct hlsl_ir_switch
{
    struct hlsl_ir_node node;
    struct hlsl_src selector;
    struct list cases;
''', '''struct hlsl_ir_switch
{
    struct hlsl_ir_node node;
    struct hlsl_src selector;
    struct list cases;
    /* fxc2: marked [forcecase] or [call]: stays a switch, see
     * lower_switch_to_ifs(). */
    bool force_case;
'''),
])

edit("hlsl.c", [
    ('''    ret = hlsl_new_switch(ctx, map_instr(map, s->selector.node), &cases, &s->node.loc);
    hlsl_cleanup_ir_switch_cases(&cases);

    return ret;
''', '''    ret = hlsl_new_switch(ctx, map_instr(map, s->selector.node), &cases, &s->node.loc);
    hlsl_cleanup_ir_switch_cases(&cases);
    if (ret)
        hlsl_ir_switch(ret)->force_case = s->force_case;

    return ret;
'''),
])

edit("hlsl.y", [
    ('''    hlsl_block_add_instr(block, s);

    cleanup_parse_attribute_list(attributes);
    return true;
}
''', '''    hlsl_block_add_instr(block, s);

    for (unsigned int i = 0; i < attributes->count; ++i)
    {
        if (!strcmp(attributes->attrs[i]->name, "forcecase") || !strcmp(attributes->attrs[i]->name, "call"))
            hlsl_ir_switch(s)->force_case = true;
    }

    cleanup_parse_attribute_list(attributes);
    return true;
}
'''),
])

LOWER = r'''/* fxc2: FXC only emits a switch instruction for a switch statement marked
 * [forcecase] (or [call]); every other one becomes a chain of if/else. Shader
 * authors tune with that in mind, and drivers do not treat the two forms
 * alike, so follow it. Runs after normalize_switch_cases(): every case with a
 * body ends in a break, and empty cases fall through to the next one.
 *
 * A break anywhere else in a case would leave the switch from inside nested
 * control flow, which an if chain cannot express; such switches are kept. */
static bool switch_block_has_inner_break(const struct hlsl_block *block, bool top_level)
{
    const struct hlsl_ir_node *instr, *last = NULL;

    if (!list_empty(&block->instrs))
        last = LIST_ENTRY(list_tail(&block->instrs), struct hlsl_ir_node, entry);

    LIST_FOR_EACH_ENTRY(instr, &block->instrs, struct hlsl_ir_node, entry)
    {
        if (instr->type == HLSL_IR_JUMP && hlsl_ir_jump(instr)->type == HLSL_IR_JUMP_BREAK)
        {
            if (!(top_level && instr == last))
                return true;
        }
        else if (instr->type == HLSL_IR_IF)
        {
            if (switch_block_has_inner_break(&hlsl_ir_if(instr)->then_block, false)
                    || switch_block_has_inner_break(&hlsl_ir_if(instr)->else_block, false))
                return true;
        }
        /* Breaks in nested loops and switches belong to those. */
    }
    return false;
}

static bool lower_switch_to_ifs(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    struct hlsl_type *bool_type = hlsl_get_scalar_type(ctx, HLSL_TYPE_BOOL);
    struct hlsl_ir_switch_case *c, *default_case = NULL;
    struct hlsl_block chain, conditions, tail;
    struct hlsl_ir_node *selector, *cond;
    struct hlsl_ir_switch *s;
    bool pending_default;

    if (instr->type != HLSL_IR_SWITCH)
        return false;
    s = hlsl_ir_switch(instr);
    if (s->force_case)
        return false;
    selector = s->selector.node;

    LIST_FOR_EACH_ENTRY(c, &s->cases, struct hlsl_ir_switch_case, entry)
    {
        if (switch_block_has_inner_break(&c->body, true))
            return false;
    }

    /* The case that the default label falls through to (or is). */
    pending_default = false;
    LIST_FOR_EACH_ENTRY(c, &s->cases, struct hlsl_ir_switch_case, entry)
    {
        if (c->is_default)
            pending_default = true;
        if (pending_default && !list_empty(&c->body.instrs))
        {
            default_case = c;
            break;
        }
    }

    /* All comparisons first, then the chain, built from its far end:
     *     if (c0) body0 else if (c1) body1 ... else default.
     * A case consisting of just "break" still needs its (empty) branch, so
     * that it does not end up in the default one. */
    hlsl_block_init(&conditions);
    hlsl_block_init(&chain);
    if (default_case)
    {
        struct hlsl_ir_node *last = LIST_ENTRY(list_tail(&default_case->body.instrs), struct hlsl_ir_node, entry);

        list_remove(&last->entry);
        hlsl_free_instr(last);
        hlsl_block_add_block(&chain, &default_case->body);
    }

    cond = NULL;
    LIST_FOR_EACH_ENTRY_REV(c, &s->cases, struct hlsl_ir_switch_case, entry)
    {
        struct hlsl_ir_node *operands[HLSL_MAX_OPERANDS] = {0}, *eq, *last;
        bool falls_through = list_empty(&c->body.instrs);

        if (c == default_case)
        {
            /* Labels falling through into the default body need no test. */
            cond = NULL;
            continue;
        }
        if (!falls_through)
            cond = NULL;
        else if (!cond)
            continue;   /* Falls through to the default body, or off the end. */

        if (c->is_default)
            continue;

        operands[0] = selector;
        operands[1] = hlsl_block_add_uint_constant(ctx, &conditions, c->value, &c->loc);
        eq = hlsl_block_add_expr(ctx, &conditions, HLSL_OP2_EQUAL, operands, bool_type, &c->loc);

        if (falls_through)
        {
            /* An empty label in front of the case whose "if" was just made:
             * widen that condition. */
            struct hlsl_ir_if *iff = hlsl_ir_if(LIST_ENTRY(list_head(&chain.instrs), struct hlsl_ir_node, entry));

            operands[0] = iff->condition.node;
            operands[1] = eq;
            cond = hlsl_block_add_expr(ctx, &conditions, HLSL_OP2_LOGIC_OR, operands, bool_type, &c->loc);
            hlsl_src_remove(&iff->condition);
            hlsl_src_from_node(&iff->condition, cond);
            continue;
        }

        last = LIST_ENTRY(list_tail(&c->body.instrs), struct hlsl_ir_node, entry);
        VKD3D_ASSERT(last->type == HLSL_IR_JUMP && hlsl_ir_jump(last)->type == HLSL_IR_JUMP_BREAK);
        list_remove(&last->entry);
        hlsl_free_instr(last);

        cond = eq;
        hlsl_block_init(&tail);
        hlsl_block_add_block(&tail, &chain);
        hlsl_block_init(&chain);
        hlsl_block_add_if(ctx, &chain, cond, &c->body, &tail, HLSL_IF_FORCE_BRANCH, false, &c->loc);
    }

    list_move_before(&instr->entry, &conditions.instrs);
    list_move_before(&instr->entry, &chain.instrs);
    list_remove(&instr->entry);
    hlsl_free_instr(instr);
    return true;
}

'''

edit("hlsl_codegen.c", [
    ('''static bool mark_indexable_var(struct hlsl_ctx *ctx, struct hlsl_deref *deref,
        struct hlsl_ir_node *instr)
{''', LOWER + '''static bool mark_indexable_var(struct hlsl_ctx *ctx, struct hlsl_deref *deref,
        struct hlsl_ir_node *instr)
{'''),
    ('''    hlsl_transform_ir(ctx, normalize_switch_cases, body, NULL);
''', '''    hlsl_transform_ir(ctx, normalize_switch_cases, body, NULL);
    if (hlsl_version_ge(ctx, 4, 0) && !hlsl_tuning_enabled("VKD3D_HLSL_SWITCH", false))
        hlsl_transform_ir(ctx, lower_switch_to_ifs, body, NULL);
'''),
])

# hlsl_tuning_enabled() is defined further down, next to load elision; declare it up front.
path = base + "hlsl_codegen.c"
s = open(path).read()
anchor = "/* fxc2: scalar replacement of aggregates."
assert s.count(anchor) == 1
s = s.replace(anchor, "static bool hlsl_tuning_enabled(const char *variable, bool default_value);\n\n" + anchor)
open(path, "w").write(s)
print("patched")
