import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/ir.c")
s = open(path).read()


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:80], s.count(old))
    s = s.replace(old, new)


# --- liveness: remember which registers are touched inside a loop ----------
rep('''        bool written;
        bool fixed_mask;
        uint8_t mask;
        unsigned int interior_loop_start, interior_loop_depth;
        unsigned int first_write, last_access, last_read;
    } *ssa_regs, *temp_regs;
};''', '''        bool written;
        bool fixed_mask;
        /* fxc2: read or written inside a loop. */
        bool in_loop;
        uint8_t mask;
        unsigned int interior_loop_start, interior_loop_depth;
        unsigned int first_write, last_access, last_read;
    } *ssa_regs, *temp_regs;
    /* fxc2: whether the instruction being tracked is inside a loop. */
    bool in_loop;
};''')

rep('''    reg->last_read = index;
    reg->last_access = index;
    if (!reg->written)
    {''', '''    reg->last_read = index;
    reg->last_access = index;
    if (tracker->in_loop)
        reg->in_loop = true;
    if (!reg->written)
    {''')

rep('''    reg->written = true;
    reg->mask |= dst->write_mask;
''', '''    reg->written = true;
    reg->mask |= dst->write_mask;
    if (tracker->in_loop)
        reg->in_loop = true;
''')

rep('''        for (unsigned int j = 0; j < ins->dst_count; ++j)
            liveness_track_dst(tracker, &ins->dst[j], i, &program->shader_version, ins->opcode);
''', '''        tracker->in_loop = !!loop_depth;
        for (unsigned int j = 0; j < ins->dst_count; ++j)
            liveness_track_dst(tracker, &ins->dst[j], i, &program->shader_version, ins->opcode);
''')

# --- allocator: loop values get a register to themselves --------------------
rep('''/* fxc2: whether values that are live at the same time may share the
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
''', '''/* fxc2: whether values that are live at the same time may share the
 * components of one register.
 *
 * Packing keeps the register count down and suits straight-line code. In a
 * loop it is costly on drivers that track registers as whole vectors: every
 * write to one value looks like a change to its neighbours, which then have to
 * be carried around the loop and merged after every branch with them. On one
 * large interpreter loop, not packing was worth 17% per iteration, while
 * packing everything made the code around the loop 7% cheaper. So the default
 * is to give values used inside a loop a register of their own and pack the
 * rest. VKD3D_PACK_REGISTERS=1 packs everything, =0 nothing. */
enum temp_allocator_packing
{
    PACK_NEVER,
    PACK_ALWAYS,
    PACK_OUTSIDE_LOOPS,
};

/* Set in current_allocation[] for a register held by a value used in a loop. */
#define TEMP_ALLOCATION_EXCLUSIVE 0x10

static enum temp_allocator_packing temp_allocator_packing(void)
{
    static int packing = -1;

    if (packing < 0)
    {
        const char *env = getenv("VKD3D_PACK_REGISTERS");

        packing = !env ? PACK_OUTSIDE_LOOPS : atoi(env) ? PACK_ALWAYS : PACK_NEVER;
    }
    return packing;
}
''')

rep('''        /* fxc2: see temp_allocator_pack_registers(). */
        if (!temp_allocator_pack_registers() && available_mask != 0xf)
            continue;
''', '''        /* fxc2: see temp_allocator_packing(). */
        if (available_mask != 0xf || (current_allocation[i] & TEMP_ALLOCATION_EXCLUSIVE))
        {
            if (temp_allocator_packing() == PACK_NEVER || (current_allocation[i] & TEMP_ALLOCATION_EXCLUSIVE)
                    || (temp_allocator_packing() == PACK_OUTSIDE_LOOPS && liveness_reg->in_loop))
                continue;
        }
''')

rep('''    VKD3D_ASSERT(k < reg_count);
    if (spread)
        cursor = (i + 1) % spread;
}
''', '''    VKD3D_ASSERT(k < reg_count);
    if (temp_allocator_packing() == PACK_OUTSIDE_LOOPS && liveness_reg->in_loop)
        current_allocation[i] |= TEMP_ALLOCATION_EXCLUSIVE;
    if (spread)
        cursor = (i + 1) % spread;
}
''')

rep('''    allocator->current_allocation[reg->temp_id] &= ~reg->allocated_mask;
}
''', '''    allocator->current_allocation[reg->temp_id] &= ~reg->allocated_mask;
    if (!(allocator->current_allocation[reg->temp_id] & 0xf))
        allocator->current_allocation[reg->temp_id] = 0;
}
''')
open(path, "w").write(s)
print("patched")
