import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:90], s.count(old))
    s = s.replace(old, new)


# --- switch_to_ifs(): usable before returns are lowered, returns the if ----
a = s.index("static bool lower_switch_to_ifs(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)")
b = s.index("static bool mark_indexable_var(struct hlsl_ctx *ctx, struct hlsl_deref *deref,")
func = s[a:b]


def frep(old, new, count=1):
    global func
    assert func.count(old) == count, (old[:90], func.count(old))
    func = func.replace(old, new)


frep("static bool lower_switch_to_ifs(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)",
     "static struct hlsl_ir_node *switch_to_ifs(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr)")
frep('''    struct hlsl_ir_node *selector, *cond;
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
''', '''    struct hlsl_ir_node *selector, *cond, *result;
    struct hlsl_ir_switch *s;
    bool pending_default, has_if = false;

    if (instr->type != HLSL_IR_SWITCH)
        return NULL;
    s = hlsl_ir_switch(instr);
    if (s->force_case)
        return NULL;
    selector = s->selector.node;

    LIST_FOR_EACH_ENTRY(c, &s->cases, struct hlsl_ir_switch_case, entry)
    {
        const struct hlsl_ir_node *last;

        if (switch_block_has_inner_break(&c->body, true))
            return NULL;
        if (list_empty(&c->body.instrs))
            continue;
        /* Every case has to end in a break, or, when this runs before
         * returns have been lowered, return on every path. */
        last = LIST_ENTRY(list_tail(&c->body.instrs), struct hlsl_ir_node, entry);
        if (!(last->type == HLSL_IR_JUMP && hlsl_ir_jump(last)->type == HLSL_IR_JUMP_BREAK)
                && !block_always_returns(&c->body))
            return NULL;
    }
''')
frep('''        if (pending_default && !list_empty(&c->body.instrs))
        {
            default_case = c;
            break;
        }
    }
''', '''        if (pending_default && !list_empty(&c->body.instrs))
        {
            default_case = c;
            break;
        }
    }

    /* Without a case to test for there is no if to make. */
    LIST_FOR_EACH_ENTRY(c, &s->cases, struct hlsl_ir_switch_case, entry)
    {
        if (c != default_case && !c->is_default && !list_empty(&c->body.instrs))
            has_if = true;
    }
    if (!has_if)
        return NULL;
''')
frep('''        struct hlsl_ir_node *last = LIST_ENTRY(list_tail(&default_case->body.instrs), struct hlsl_ir_node, entry);

        list_remove(&last->entry);
        hlsl_free_instr(last);
        hlsl_block_add_block(&chain, &default_case->body);
''', '''        struct hlsl_ir_node *last = LIST_ENTRY(list_tail(&default_case->body.instrs), struct hlsl_ir_node, entry);

        if (last->type == HLSL_IR_JUMP && hlsl_ir_jump(last)->type == HLSL_IR_JUMP_BREAK)
        {
            list_remove(&last->entry);
            hlsl_free_instr(last);
        }
        hlsl_block_add_block(&chain, &default_case->body);
''')
frep('''        last = LIST_ENTRY(list_tail(&c->body.instrs), struct hlsl_ir_node, entry);
        VKD3D_ASSERT(last->type == HLSL_IR_JUMP && hlsl_ir_jump(last)->type == HLSL_IR_JUMP_BREAK);
        list_remove(&last->entry);
        hlsl_free_instr(last);
''', '''        last = LIST_ENTRY(list_tail(&c->body.instrs), struct hlsl_ir_node, entry);
        if (last->type == HLSL_IR_JUMP && hlsl_ir_jump(last)->type == HLSL_IR_JUMP_BREAK)
        {
            list_remove(&last->entry);
            hlsl_free_instr(last);
        }
''')
frep('''    list_move_before(&instr->entry, &conditions.instrs);
    list_move_before(&instr->entry, &chain.instrs);
    list_remove(&instr->entry);
    hlsl_free_instr(instr);
    return true;
}
''', '''    /* The chain is a single if, with everything else inside it. */
    result = LIST_ENTRY(list_head(&chain.instrs), struct hlsl_ir_node, entry);
    VKD3D_ASSERT(result->type == HLSL_IR_IF);

    list_move_before(&instr->entry, &conditions.instrs);
    list_move_before(&instr->entry, &chain.instrs);
    list_remove(&instr->entry);
    hlsl_free_instr(instr);
    return result;
}

static bool lower_switch_to_ifs(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    return !!switch_to_ifs(ctx, instr);
}
''')
s = s[:a] + func + s[b:]

# --- lower_return(): turn switches that return into ifs first ---------------
rep('''static bool hlsl_tuning_enabled(const char *variable, bool default_value);

/* fxc2: number of instructions in a block, nested ones included, up to a''',
    '''static bool hlsl_tuning_enabled(const char *variable, bool default_value);
static struct hlsl_ir_node *switch_to_ifs(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr);

/* fxc2: number of instructions in a block, nested ones included, up to a''')

rep('''    LIST_FOR_EACH_ENTRY_SAFE(instr, next, &block->instrs, struct hlsl_ir_node, entry)
    {
        if (instr->type == HLSL_IR_CALL)
        {
            struct hlsl_ir_call *call = hlsl_ir_call(instr);

            lower_return(ctx, call->decl, &call->decl->body, false);
        }
''', '''    LIST_FOR_EACH_ENTRY_SAFE(instr, next, &block->instrs, struct hlsl_ir_node, entry)
    {
        /* fxc2: a return inside a switch case otherwise needs a flag, a break
         * and a test after the switch. As a chain of ifs it is handled like
         * any other return in an if, usually with none of the three. */
        if (instr->type == HLSL_IR_SWITCH && hlsl_version_ge(ctx, 4, 0)
                && hlsl_tuning_enabled("VKD3D_HLSL_RETURN_SWITCH", true))
        {
            struct hlsl_ir_switch_case *c;
            struct hlsl_ir_node *chain;
            bool returns = false;

            LIST_FOR_EACH_ENTRY(c, &hlsl_ir_switch(instr)->cases, struct hlsl_ir_switch_case, entry)
                returns |= block_contains_return(&c->body);
            if (returns && (chain = switch_to_ifs(ctx, instr)))
                instr = chain;
        }

        if (instr->type == HLSL_IR_CALL)
        {
            struct hlsl_ir_call *call = hlsl_ir_call(instr);

            lower_return(ctx, call->decl, &call->decl->body, false);
        }
''')

rep("        limit = env ? atoi(env) : 24;", "        limit = env ? atoi(env) : 200;")
open(path, "w").write(s)
print("patched")
