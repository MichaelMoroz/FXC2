import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


# Per-variable state of adce_execute() and alias_inout_arrays() was reset by
# going through the scopes; variables made without a scope kept what an
# earlier run left (a set "needed" mark, so that their stores were not marked
# on the second run and went). Reset it from the code instead.
rep('''static bool adce_execute(struct hlsl_ctx *ctx, struct hlsl_block *body)
{''', '''static void adce_reset_var(struct hlsl_ir_var *var)
{
    if (!var)
        return;
    var->adce_store_count = 0;
    var->adce_live = false;
    var->adce_seen = false;
    var->adce_rename = NULL;
}

/* Not every variable is in a scope's list; go by what the code refers to. */
static bool adce_reset(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    switch (instr->type)
    {
        case HLSL_IR_LOAD:
            adce_reset_var(hlsl_ir_load(instr)->src.var);
            break;
        case HLSL_IR_STORE:
            adce_reset_var(hlsl_ir_store(instr)->lhs.var);
            break;
        case HLSL_IR_RESOURCE_LOAD:
            adce_reset_var(hlsl_ir_resource_load(instr)->resource.var);
            adce_reset_var(hlsl_ir_resource_load(instr)->sampler.var);
            break;
        case HLSL_IR_RESOURCE_STORE:
            adce_reset_var(hlsl_ir_resource_store(instr)->resource.var);
            break;
        case HLSL_IR_INTERLOCKED:
            adce_reset_var(hlsl_ir_interlocked(instr)->dst.var);
            break;
        default:
            break;
    }
    return false;
}

static bool adce_execute(struct hlsl_ctx *ctx, struct hlsl_block *body)
{''')
rep('''            var->adce_store_count = 0;
            var->adce_live = false;
            var->adce_seen = false;
            var->adce_rename = NULL;
        }
    }
''', '''            adce_reset_var(var);
        }
    }
    hlsl_transform_ir(ctx, adce_reset, body, NULL);
''')

rep('''static bool alias_collect(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{''', '''static bool alias_reset(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    struct hlsl_ir_var *var = NULL;

    if (instr->type == HLSL_IR_LOAD)
        var = hlsl_ir_load(instr)->src.var;
    else if (instr->type == HLSL_IR_STORE)
        var = hlsl_ir_store(instr)->lhs.var;
    if (var)
    {
        var->alias_parent = var->alias_root = NULL;
        var->alias_member = var->alias_invalid = false;
    }
    return false;
}

static bool alias_collect(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{''')
rep('''    hlsl_transform_ir(ctx, alias_collect, body, NULL);
    hlsl_transform_ir(ctx, alias_validate, body, NULL);
''', '''    hlsl_transform_ir(ctx, alias_reset, body, NULL);
    hlsl_transform_ir(ctx, alias_collect, body, NULL);
    hlsl_transform_ir(ctx, alias_validate, body, NULL);
''')
# A member that is in no scope cannot be checked below: do not use its set.
rep('''    if (!deref->var->alias_member || (set = alias_find(deref->var))->alias_invalid || !set->alias_root)
        return false;
''', '''    if (!deref->var->alias_member || (set = alias_find(deref->var))->alias_invalid || !set->alias_root
            || !deref->var->alias_checked)
        return false;
''')
rep('''            if (!var->alias_member)
                continue;
            set = alias_find(var);
            any = true;
''', '''            if (!var->alias_member)
                continue;
            set = alias_find(var);
            any = true;
            var->alias_checked = true;
''')
rep('''    if (var)
    {
        var->alias_parent = var->alias_root = NULL;
        var->alias_member = var->alias_invalid = false;
    }
    return false;''', '''    if (var)
    {
        var->alias_parent = var->alias_root = NULL;
        var->alias_member = var->alias_invalid = var->alias_checked = false;
    }
    return false;''')
open(path, "w").write(s)

path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.h")
s = open(path).read()
rep('''    bool alias_member, alias_invalid;''', '''    bool alias_member, alias_invalid, alias_checked;''')
open(path, "w").write(s)
print("patched")
