import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


# Compile time on shaders of several hundred thousand instructions (Poiyomi
# with everything switched on): two things were quadratic or close to it.
rep('''    for (size_t i = 0; i < state->count; ++i)
    {
        struct vectorizable_exprs_group *group = &state->groups[i];
        struct hlsl_ir_expr *other = group->exprs[0];
''', '''    /* fxc2: every expression was compared with every group found so far,
     * which is half the compile time of a very large shader. What can go
     * into one vector instruction is computed close together; look at the
     * most recent groups only. */
    for (size_t i = state->count > 256 ? state->count - 256 : 0; i < state->count; ++i)
    {
        struct vectorizable_exprs_group *group = &state->groups[i];
        struct hlsl_ir_expr *other = group->exprs[0];
''')
rep('''static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{
    const unsigned int max_cost = flatten_max_cost();
    struct hlsl_ir_node *instr;
    unsigned int cost = 0;
''', '''static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{
    /* fxc2: read the environment once, not for every load and store. */
    static int keep_array_branches = -1;
    const unsigned int max_cost = flatten_max_cost();
    struct hlsl_ir_node *instr;
    unsigned int cost = 0;

    if (keep_array_branches < 0)
        keep_array_branches = hlsl_tuning_enabled("VKD3D_HLSL_KEEP_ARRAY_BRANCHES", true);
''')
rep('''                if (deref_has_dynamic_index(&hlsl_ir_store(instr)->lhs)
                        && hlsl_tuning_enabled("VKD3D_HLSL_KEEP_ARRAY_BRANCHES", true))
                    return false;
                ++cost;
''', '''                if (keep_array_branches && deref_has_dynamic_index(&hlsl_ir_store(instr)->lhs))
                    return false;
                ++cost;
''')
rep('''                if (deref_has_dynamic_index(&hlsl_ir_load(instr)->src)
                        && hlsl_tuning_enabled("VKD3D_HLSL_KEEP_ARRAY_BRANCHES", true))
                    return false;
''', '''                if (keep_array_branches && deref_has_dynamic_index(&hlsl_ir_load(instr)->src))
                    return false;
''')
open(p, "w").write(s)
print("patched")
