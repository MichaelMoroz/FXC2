import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/ir.c")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep('''static void temp_allocator_open_register(struct temp_allocator *allocator, struct temp_allocator_reg *reg)
{
    const size_t reg_count = allocator->ssa_count + allocator->temp_count;
    const struct liveness_tracker_reg *liveness_reg = reg->liveness_reg;
    uint8_t *current_allocation = allocator->current_allocation;
    size_t i;

    if (!liveness_reg->written)
        return;

    for (i = 0; i < reg_count; ++i)
    {
        const uint8_t available_mask = ~current_allocation[i] & 0xf;
''', '''/* fxc2: with VKD3D_REGISTER_SPREAD=<n>, free registers are handed out in
 * rotation over the first <n> instead of lowest first, so that unrelated
 * short-lived values in different branches tend not to land in the same
 * register. 0 (the default) is lowest first. */
static size_t temp_allocator_spread(void)
{
    static int spread = -1;

    if (spread < 0)
    {
        const char *env = getenv("VKD3D_REGISTER_SPREAD");

        spread = env ? atoi(env) : 0;
    }
    return spread;
}

static void temp_allocator_open_register(struct temp_allocator *allocator, struct temp_allocator_reg *reg)
{
    const size_t reg_count = allocator->ssa_count + allocator->temp_count;
    const struct liveness_tracker_reg *liveness_reg = reg->liveness_reg;
    uint8_t *current_allocation = allocator->current_allocation;
    const size_t spread = min(temp_allocator_spread(), reg_count);
    static size_t cursor;
    size_t i = 0, k;

    if (!liveness_reg->written)
        return;

    for (k = 0; k < reg_count; ++k)
    {
        const uint8_t available_mask = ~current_allocation[i = k < spread ? (cursor + k) % spread : k] & 0xf;
''')
rep('''    VKD3D_ASSERT(i < reg_count);
}

static void temp_allocator_close_register(''', '''    VKD3D_ASSERT(k < reg_count);
    if (spread)
        cursor = (i + 1) % spread;
}

static void temp_allocator_close_register(''')
open(path, "w").write(s)
print("patched")
