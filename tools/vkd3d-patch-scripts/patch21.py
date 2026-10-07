import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()
old = '''static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{
    static const unsigned int max_cost = 10;
    struct hlsl_ir_node *instr;
    unsigned int cost = 0;
'''
new = '''static bool hlsl_tuning_enabled(const char *variable, bool default_value);

/* fxc2: how many expressions and stores an if or else block may hold and still
 * be turned into conditional moves when the source does not say [branch] or
 * [flatten]. VKD3D_HLSL_FLATTEN overrides it; 0 never flattens. */
static unsigned int flatten_max_cost(void)
{
    static int cost = -1;

    if (cost < 0)
    {
        const char *env = getenv("VKD3D_HLSL_FLATTEN");

        cost = env ? atoi(env) : 10;
    }
    return cost;
}

static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{
    const unsigned int max_cost = flatten_max_cost();
    struct hlsl_ir_node *instr;
    unsigned int cost = 0;

    if (!max_cost)
        return false;
'''
assert s.count(old) == 1
s = s.replace(old, new)
# the earlier forward declaration of hlsl_tuning_enabled now comes later in the file; a second
# identical declaration is harmless.
open(path, "w").write(s)
print("patched")
