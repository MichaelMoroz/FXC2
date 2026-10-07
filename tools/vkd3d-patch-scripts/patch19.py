import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()
old = '''    if (hlsl_version_lt(ctx, 4, 0) || liveness_loops_too_deep || !instr->last_read || !instr->last_use)
        return false;
'''
new = '''    if (hlsl_version_lt(ctx, 4, 0) || liveness_loops_too_deep || !instr->last_read || !instr->last_use)
        return false;
    if (!hlsl_tuning_enabled("VKD3D_HLSL_ELIDE_LOADS", true))
        return false;
'''
assert s.count(old) == 1
s = s.replace(old, new)
old = '''static bool load_can_be_elided(struct hlsl_ctx *ctx, const struct hlsl_ir_load *load)
{'''
new = '''/* fxc2: switches for measuring what each optimisation is worth on a given
 * driver: VARIABLE=0 turns one off, VARIABLE=1 on. */
static bool hlsl_tuning_enabled(const char *variable, bool default_value)
{
    const char *env = getenv(variable);

    return env ? !!atoi(env) : default_value;
}

static bool load_can_be_elided(struct hlsl_ctx *ctx, const struct hlsl_ir_load *load)
{'''
assert s.count(old) == 1
s = s.replace(old, new)

old = '''    if (hlsl_version_ge(ctx, 4, 0) && lvn_execute(ctx, body))
        hlsl_run_folding_passes(ctx, body);
'''
new = '''    if (hlsl_version_ge(ctx, 4, 0) && hlsl_tuning_enabled("VKD3D_HLSL_VALUE_NUMBERING", true)
            && lvn_execute(ctx, body))
        hlsl_run_folding_passes(ctx, body);
'''
assert s.count(old) == 1
s = s.replace(old, new)

old = '''    if (hlsl_version_ge(ctx, 4, 0) && sroa_execute(ctx, body))
        hlsl_run_const_passes(ctx, body);
'''
new = '''    if (hlsl_version_ge(ctx, 4, 0) && hlsl_tuning_enabled("VKD3D_HLSL_SPLIT_STRUCTS", true)
            && sroa_execute(ctx, body))
        hlsl_run_const_passes(ctx, body);
'''
assert s.count(old) == 1
s = s.replace(old, new)
# the helper must precede its first use (sroa is called from process_entry_function, later in the file;
# lvn likewise), so nothing else to move.
open(path, "w").write(s)
print("patched")
