import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/ir.c")
s = open(path).read()
old = '''    for (i = 0; i < reg_count; ++i)
    {
        const uint8_t available_mask = ~current_allocation[i] & 0xf;

        if (liveness_reg->fixed_mask)
'''
new = '''    for (i = 0; i < reg_count; ++i)
    {
        const uint8_t available_mask = ~current_allocation[i] & 0xf;

        /* fxc2: see temp_allocator_pack_registers(). */
        if (!temp_allocator_pack_registers() && available_mask != 0xf)
            continue;

        if (liveness_reg->fixed_mask)
'''
assert s.count(old) == 1
s = s.replace(old, new)
old = '''static void temp_allocator_open_register(struct temp_allocator *allocator, struct temp_allocator_reg *reg)
{'''
new = '''/* fxc2: whether values that are live at the same time may share the
 * components of one register. Packing keeps the register count down, but a
 * driver that tracks registers as whole vectors then sees every write to one
 * value as a change to its neighbours. Controlled by VKD3D_PACK_REGISTERS. */
static bool temp_allocator_pack_registers(void)
{
    static int pack = -1;

    if (pack < 0)
    {
        const char *env = getenv("VKD3D_PACK_REGISTERS");

        pack = env ? !!atoi(env) : 1;
    }
    return pack;
}

static void temp_allocator_open_register(struct temp_allocator *allocator, struct temp_allocator_reg *reg)
{'''
assert s.count(old) == 1
s = s.replace(old, new)
open(path, "w").write(s)
print("patched")
