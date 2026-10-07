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
    ('''    /* Whether the shader performs dereferences with non-constant offsets in the variable. */
    bool indexable;
''', '''    /* Whether the shader performs dereferences with non-constant offsets in the variable. */
    bool indexable;
    /* fxc2: scalar replacement of struct variables, see sroa_execute(). */
    bool sroa_blocked;
    struct hlsl_ir_var **sroa_fields;
'''),
])

edit("hlsl_codegen.c", [
    ('''static bool mark_indexable_var(struct hlsl_ctx *ctx, struct hlsl_deref *deref,
        struct hlsl_ir_node *instr)
{''', '''/* fxc2: scalar replacement of aggregates.
 *
 * A variable is given an indexable temp, i.e. memory rather than registers,
 * as soon as anything in it is addressed with a non-constant index. For a
 * struct that holds one such array next to dozens of scalars (the state of an
 * emulated CPU, say) that put every field in memory. Split struct variables
 * into one variable per field wherever every access names a field, so that
 * only the arrays that need it stay indexable. Nested structs are handled by
 * repeating until nothing changes. */
static void run_dead_code_elimination_passes(struct hlsl_ctx *ctx, struct hlsl_block *body);

static bool sroa_type_is_numeric(const struct hlsl_type *type)
{
    size_t i;

    if (type->class <= HLSL_CLASS_LAST_NUMERIC)
        return true;
    if (type->class == HLSL_CLASS_ARRAY)
        return sroa_type_is_numeric(type->e.array.type);
    if (type->class != HLSL_CLASS_STRUCT)
        return false;
    for (i = 0; i < type->e.record.field_count; ++i)
    {
        if (!sroa_type_is_numeric(type->e.record.fields[i].type))
            return false;
    }
    return true;
}

static bool sroa_var_is_candidate(const struct hlsl_ir_var *var)
{
    return var->data_type->class == HLSL_CLASS_STRUCT && !var->is_uniform && !var->is_input_semantic
            && !var->is_output_semantic && !var->is_tgsm && !var->is_separated_resource
            && sroa_type_is_numeric(var->data_type);
}

static void sroa_note_deref(const struct hlsl_deref *deref, bool splittable_use)
{
    if (!deref->var)
        return;
    if (!splittable_use || !deref->path_len || deref->path[0].node->type != HLSL_IR_CONSTANT)
        deref->var->sroa_blocked = true;
}

static bool sroa_reset(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    if (instr->type == HLSL_IR_LOAD)
        hlsl_ir_load(instr)->src.var->sroa_blocked = false;
    else if (instr->type == HLSL_IR_STORE)
        hlsl_ir_store(instr)->lhs.var->sroa_blocked = false;
    return false;
}

static bool sroa_scan(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    switch (instr->type)
    {
        case HLSL_IR_LOAD:
            sroa_note_deref(&hlsl_ir_load(instr)->src, true);
            break;

        case HLSL_IR_STORE:
            sroa_note_deref(&hlsl_ir_store(instr)->lhs, true);
            break;

        case HLSL_IR_RESOURCE_LOAD:
            sroa_note_deref(&hlsl_ir_resource_load(instr)->resource, false);
            sroa_note_deref(&hlsl_ir_resource_load(instr)->sampler, false);
            break;

        case HLSL_IR_RESOURCE_STORE:
            sroa_note_deref(&hlsl_ir_resource_store(instr)->resource, false);
            break;

        case HLSL_IR_INTERLOCKED:
            sroa_note_deref(&hlsl_ir_interlocked(instr)->dst, false);
            break;

        default:
            break;
    }
    return false;
}

static bool sroa_rewrite_deref(struct hlsl_ctx *ctx, struct hlsl_deref *deref, struct hlsl_ir_node *instr)
{
    struct hlsl_ir_var *var = deref->var, *field_var;
    struct hlsl_deref new_deref;
    unsigned int idx, i;

    if (instr->type != HLSL_IR_LOAD && instr->type != HLSL_IR_STORE)
        return false;
    if (!var || var->sroa_blocked || !sroa_var_is_candidate(var))
        return false;

    idx = hlsl_ir_constant(deref->path[0].node)->value.u[0].u;
    VKD3D_ASSERT(idx < var->data_type->e.record.field_count);

    if (!var->sroa_fields && !(var->sroa_fields = hlsl_calloc(ctx,
            var->data_type->e.record.field_count, sizeof(*var->sroa_fields))))
        return false;
    if (!(field_var = var->sroa_fields[idx]))
    {
        if (!(field_var = hlsl_new_synthetic_var(ctx, "sroa",
                var->data_type->e.record.fields[idx].type, &var->loc)))
            return false;
        var->sroa_fields[idx] = field_var;
    }

    if (!hlsl_deref_init(&new_deref, field_var, deref->path_len - 1, ctx))
        return false;
    for (i = 0; i < new_deref.path_len; ++i)
        hlsl_src_from_node(&new_deref.path[i], deref->path[i + 1].node);
    hlsl_deref_cleanup(deref);
    *deref = new_deref;
    return true;
}

static bool sroa_execute(struct hlsl_ctx *ctx, struct hlsl_block *body)
{
    bool progress, any_progress = false;

    /* Whole-struct loads left behind by split_copies() would block this. */
    run_dead_code_elimination_passes(ctx, body);
    do
    {
        hlsl_transform_ir(ctx, sroa_reset, body, NULL);
        hlsl_transform_ir(ctx, sroa_scan, body, NULL);
        progress = transform_derefs(ctx, sroa_rewrite_deref, body);
        any_progress |= progress;
    } while (progress);

    return any_progress;
}

static bool mark_indexable_var(struct hlsl_ctx *ctx, struct hlsl_deref *deref,
        struct hlsl_ir_node *instr)
{'''),
    ('''    remove_unreachable_code(ctx, body);
    hlsl_transform_ir(ctx, normalize_switch_cases, body, NULL);

    replace_ir(ctx, lower_vector_derefs, body);
''', '''    remove_unreachable_code(ctx, body);
    hlsl_transform_ir(ctx, normalize_switch_cases, body, NULL);

    if (hlsl_version_ge(ctx, 4, 0) && sroa_execute(ctx, body))
        hlsl_run_const_passes(ctx, body);

    replace_ir(ctx, lower_vector_derefs, body);
'''),
])

edit("hlsl.c", [
    ('''    vkd3d_free((void *)decl->name);
''', '''    vkd3d_free((void *)decl->name);
    vkd3d_free(decl->sroa_fields);
'''),
])
print("patched")
