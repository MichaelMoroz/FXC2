import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


rep('''static bool simplify_exprs(struct hlsl_ctx *ctx, struct hlsl_block *block)
{
    bool progress, any_progress = false;

    do
    {
        progress = replace_ir(ctx, hlsl_fold_constant_exprs, block);
        progress |= replace_ir(ctx, hlsl_fold_binary_exprs, block);
        progress |= replace_ir(ctx, fold_unary_identities, block);
        progress |= replace_ir(ctx, fold_conditional_identities, block);
        progress |= replace_ir(ctx, hlsl_fold_constant_identities, block);
        progress |= replace_ir(ctx, hlsl_fold_constant_swizzles, block);

        any_progress |= progress;
    } while (progress);

    return any_progress;
}
''', '''/* fxc2: several replace functions in one walk of the program. The folding
 * passes were a walk each, six of them in a loop inside another loop, and
 * walking a large shader's instructions was a quarter of the time of compiling
 * it, most of it for passes that found nothing to do.
 * VKD3D_HLSL_MERGE_FOLDS=0 is a walk each again. */
struct replace_funcs
{
    const PFN_replace_func *funcs;
    unsigned int count;
};

static bool call_replace_funcs(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{
    const struct replace_funcs *funcs = context;
    unsigned int i;

    for (i = 0; i < funcs->count; ++i)
    {
        if (call_replace_func(ctx, instr, funcs->funcs[i]))
            return true;
    }
    return false;
}

static bool replace_ir_merged(struct hlsl_ctx *ctx, const PFN_replace_func *funcs, unsigned int count,
        struct hlsl_block *block)
{
    struct replace_funcs context = {funcs, count};
    static int merge = -1;
    bool progress = false;
    unsigned int i;

    if (merge < 0)
    {
        const char *e = getenv("VKD3D_HLSL_MERGE_FOLDS");

        merge = !(e && *e == '0');
    }
    if (merge)
        return hlsl_transform_ir(ctx, call_replace_funcs, block, &context);

    for (i = 0; i < count; ++i)
        progress |= replace_ir(ctx, funcs[i], block);
    return progress;
}

static bool simplify_exprs(struct hlsl_ctx *ctx, struct hlsl_block *block)
{
    static const PFN_replace_func funcs[] =
    {
        hlsl_fold_constant_exprs,
        hlsl_fold_binary_exprs,
        fold_unary_identities,
        fold_conditional_identities,
        hlsl_fold_constant_identities,
        hlsl_fold_constant_swizzles,
    };
    bool progress, any_progress = false;

    do
    {
        progress = replace_ir_merged(ctx, funcs, ARRAY_SIZE(funcs), block);

        any_progress |= progress;
    } while (progress);

    return any_progress;
}
''')

rep('''        progress |= hlsl_copy_propagation_execute(ctx, body);
        progress |= replace_ir(ctx, fold_swizzle_chains, body);
        progress |= replace_ir(ctx, fold_trivial_swizzles, body);
        progress |= hlsl_transform_ir(ctx, remove_trivial_conditional_branches, body, NULL);
''', '''        progress |= hlsl_copy_propagation_execute(ctx, body);
        progress |= replace_ir_merged(ctx, swizzle_funcs, ARRAY_SIZE(swizzle_funcs), body);
        progress |= hlsl_transform_ir(ctx, remove_trivial_conditional_branches, body, NULL);
''')
rep('''static bool hlsl_run_folding_passes(struct hlsl_ctx *ctx, struct hlsl_block *body)
{
    bool progress, any_progress;
''', '''static bool hlsl_run_folding_passes(struct hlsl_ctx *ctx, struct hlsl_block *body)
{
    static const PFN_replace_func swizzle_funcs[] = {fold_swizzle_chains, fold_trivial_swizzles};
    bool progress, any_progress;
''')
open(p, "w").write(s)
print("patched")
