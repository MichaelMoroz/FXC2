import os
import re
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:80], s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("hlsl.h", [
    ('''    /* fxc2: for adce_split_live_ranges(): whether the variable was referenced
''', '''    /* fxc2: for alias_inout_arrays(): the set of variables this one is copied
     * to and from as a whole (a union-find parent), whether it is in one, and,
     * on the representative, the variable that will stand for them all and
     * whether the set does not qualify. */
    struct hlsl_ir_var *alias_parent, *alias_root;
    bool alias_member, alias_invalid;
    /* fxc2: for adce_split_live_ranges(): whether the variable was referenced
'''),
])

PASS = r'''/* fxc2: array arguments by reference.
 *
 * An inout parameter is copied in before the call and out after it. For an
 * array that is a copy of every element each way, and a function that hands
 * its array on to the functions it calls does that at every level: a 1024
 * entry cache passed down through a dozen functions became two megabytes of
 * element copies, which the driver then would not compile.
 *
 * When the argument is always a local array (or the caller's own such
 * parameter), the function cannot see it under any other name while it runs,
 * so working on the caller's array directly is indistinguishable from working
 * on a copy and copying that back. That is what this does: it collects
 * variables connected by whole-array copies into sets and, where a set is one
 * local array and inout parameters that are only ever copied from and to
 * members of the set, makes them the same variable and removes the copies. */
static struct hlsl_ir_var *alias_find(struct hlsl_ir_var *var)
{
    while (var->alias_parent)
        var = var->alias_parent;
    return var;
}

static bool alias_candidate_type(const struct hlsl_type *type)
{
    return type->class == HLSL_CLASS_ARRAY && hlsl_is_numeric_type(hlsl_get_multiarray_element_type(type));
}

/* "a = b" for whole arrays, of which at least one is a parameter. */
static bool alias_is_copy(const struct hlsl_ir_node *instr)
{
    const struct hlsl_ir_store *store;
    const struct hlsl_ir_load *load;

    if (instr->type != HLSL_IR_STORE)
        return false;
    store = hlsl_ir_store(instr);
    if (store->lhs.path_len || store->rhs.node->type != HLSL_IR_LOAD)
        return false;
    load = hlsl_ir_load(store->rhs.node);
    return !load->src.path_len && load->src.var != store->lhs.var
            && (load->src.var->is_param || store->lhs.var->is_param)
            && alias_candidate_type(store->lhs.var->data_type)
            && hlsl_types_are_equal(store->lhs.var->data_type, load->src.var->data_type);
}

static bool alias_collect(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    struct hlsl_ir_var *a, *b;

    instr->adce_live = false;
    if (!alias_is_copy(instr))
        return false;

    /* Marks the load as one that only feeds a copy; see alias_validate(). */
    hlsl_ir_store(instr)->rhs.node->adce_live = true;
    a = hlsl_ir_store(instr)->lhs.var;
    b = hlsl_ir_load(hlsl_ir_store(instr)->rhs.node)->src.var;
    a->alias_member = b->alias_member = true;
    a = alias_find(a);
    b = alias_find(b);
    if (a != b)
        a->alias_parent = b;
    return false;
}

static bool alias_validate(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    if (instr->type == HLSL_IR_STORE)
    {
        const struct hlsl_ir_store *store = hlsl_ir_store(instr);

        /* Assigned as a whole from something else. */
        if (store->lhs.var->alias_member && !store->lhs.path_len && !alias_is_copy(instr))
            alias_find(store->lhs.var)->alias_invalid = true;
    }
    else if (instr->type == HLSL_IR_LOAD)
    {
        const struct hlsl_ir_load *load = hlsl_ir_load(instr);

        /* Read as a whole for something else than a copy. (What an argument
         * was computed as, and the value of the assignment back to it, are
         * loads nothing uses.) */
        if (load->src.var->alias_member && !load->src.path_len && !list_empty(&instr->uses)
                && (!instr->adce_live || list_count(&instr->uses) != 1))
            alias_find(load->src.var)->alias_invalid = true;
    }
    return false;
}

static bool alias_apply(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    struct hlsl_deref *deref;
    struct hlsl_ir_var *set;

    if (instr->type == HLSL_IR_STORE)
        deref = &hlsl_ir_store(instr)->lhs;
    else if (instr->type == HLSL_IR_LOAD)
        deref = &hlsl_ir_load(instr)->src;
    else
        return false;

    if (!deref->var->alias_member || (set = alias_find(deref->var))->alias_invalid || !set->alias_root)
        return false;

    if (instr->type == HLSL_IR_STORE && !deref->path_len && hlsl_ir_store(instr)->rhs.node->adce_live)
    {
        /* A copy within the set (its other side may have been renamed
         * already): now of the array to itself. */
        list_remove(&instr->entry);
        hlsl_free_instr(instr);
        return true;
    }
    if (deref->var == set->alias_root)
        return false;
    deref->var = set->alias_root;
    return true;
}

static void alias_inout_arrays(struct hlsl_ctx *ctx, struct hlsl_block *body)
{
    struct hlsl_ir_var *var, *other, *set;
    struct hlsl_scope *scope;
    bool any = false;

    LIST_FOR_EACH_ENTRY(scope, &ctx->scopes, struct hlsl_scope, entry)
    {
        LIST_FOR_EACH_ENTRY(var, &scope->vars, struct hlsl_ir_var, scope_entry)
        {
            var->alias_parent = var->alias_root = NULL;
            var->alias_member = var->alias_invalid = false;
        }
    }

    hlsl_transform_ir(ctx, alias_collect, body, NULL);
    hlsl_transform_ir(ctx, alias_validate, body, NULL);

    LIST_FOR_EACH_ENTRY(scope, &ctx->scopes, struct hlsl_scope, entry)
    {
        LIST_FOR_EACH_ENTRY(var, &scope->vars, struct hlsl_ir_var, scope_entry)
        {
            if (!var->alias_member)
                continue;
            set = alias_find(var);
            any = true;

            if (!var->is_param)
            {
                /* The one array the others are views of. A global one could be
                 * used by name in a function it was also passed to. */
                if (set->alias_root || scope == ctx->globals || var->is_uniform
                        || var->is_input_semantic || var->is_output_semantic || var->is_tgsm)
                    set->alias_invalid = true;
                set->alias_root = var;
                continue;
            }

            if (!(var->storage_modifiers & HLSL_STORAGE_IN) || !(var->storage_modifiers & HLSL_STORAGE_OUT))
                set->alias_invalid = true;
            /* Two parameters of one function would be the same array to it. */
            LIST_FOR_EACH_ENTRY(other, &scope->vars, struct hlsl_ir_var, scope_entry)
            {
                if (other != var && other->alias_member && alias_find(other) == set)
                    set->alias_invalid = true;
            }
        }
    }

    if (any && hlsl_tuning_enabled("VKD3D_HLSL_ALIAS_ARRAYS", true))
        hlsl_transform_ir(ctx, alias_apply, body, NULL);
}

'''

path = base + "hlsl_codegen.c"
s = open(path).read()
anchor = "static void process_entry_function(struct hlsl_ctx *ctx, struct vsir_program *program,"
assert s.count(anchor) == 1
s = s.replace(anchor, PASS + anchor)
old = '''    hlsl_lower_index_loads(ctx, body);

    split_copies(ctx, body);
    replace_ir(ctx, lower_resource_stores, body);
'''
assert s.count(old) == 1
s = s.replace(old, '''    hlsl_lower_index_loads(ctx, body);

    if (hlsl_version_ge(ctx, 4, 0))
        alias_inout_arrays(ctx, body);

    split_copies(ctx, body);
    replace_ir(ctx, lower_resource_stores, body);
''')
# hlsl_tuning_enabled() is defined further up only as a declaration in places; make sure one is visible.
if s.index("static bool hlsl_tuning_enabled(const char *variable, bool default_value)") > s.index("static struct hlsl_ir_var *alias_find"):
    s = s.replace("/* fxc2: array arguments by reference.", "static bool hlsl_tuning_enabled(const char *variable, bool default_value);\n\n/* fxc2: array arguments by reference.", 1)
open(path, "w").write(s)
print("patched")

# The propagation of "var[i]" to "x[c * i + d]" reads x where var is loaded,
# not where var was assigned from it, and nothing checks that x is still what
# it was then. With an array copied into a parameter and back (which is every
# inout array argument) that is wrong, and it also never terminates: each of
# the two arrays is forever replaced by the other.
edit("hlsl_codegen.c", [
    ('''        if (!x)
            x = idx->src.var;
        else if (x != idx->src.var)
            goto done;
''', '''        if (!x)
            x = idx->src.var;
        else if (x != idx->src.var)
            goto done;

        /* fxc2: the load from x is moved to here; that needs x to be the
         * same here as where the value was taken from it, which nothing
         * establishes, except for what never changes. Two arrays assigned to
         * each other (an inout argument) were replaced by one another forever. */
        if (!x->is_uniform)
            goto done;
'''),
])
print("patched 2")
