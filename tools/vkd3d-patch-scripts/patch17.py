import os
import re
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
    ('''    /* fxc2: bumped by every store to the variable while value numbering,
''', '''    /* fxc2: liveness indices of the stores to the variable, in order; see
     * load_can_be_elided(). */
    unsigned int *store_indices;
    size_t store_count, store_capacity;
    /* fxc2: bumped by every store to the variable while value numbering,
'''),
    ('''struct hlsl_ir_load
{
    struct hlsl_ir_node node;
    struct hlsl_deref src;
''', '''struct hlsl_ir_load
{
    struct hlsl_ir_node node;
    struct hlsl_deref src;
    /* fxc2: no instruction is generated; users read the variable's own
     * register. */
    bool elided;
'''),
])

# struct hlsl_ir_node: add exact last use and loop depth next to last_read.
path = base + "hlsl.h"
s = open(path).read()
m = re.search(r"struct hlsl_ir_node\n\{.*?\n\};", s, re.S)
node = m.group(0)
assert node.count("    unsigned int index, last_read;") == 1, node
node2 = node.replace("    unsigned int index, last_read;", '''    unsigned int index, last_read;
    /* fxc2: where the value is really last needed, which unlike last_read is
     * only pushed to the end of a loop for values defined outside that loop;
     * and the number of loops enclosing the definition. */
    unsigned int last_use, loop_depth;''')
s = s.replace(node, node2)
open(path, "w").write(s)

path = base + "hlsl_codegen.c"
s = open(path).read()

# --- liveness: record exact last uses and store positions -----------------
a = s.index("static void deref_mark_last_read(struct hlsl_deref *deref, unsigned int last_read)")
b = s.index("static void compute_liveness(struct hlsl_ctx *ctx, struct hlsl_block *body)")
region = s[a:b]

region = region.replace('''static void deref_mark_last_read(struct hlsl_deref *deref, unsigned int last_read)
{
    unsigned int i;

    if (hlsl_deref_is_lowered(deref))
    {
        if (deref->rel_offset.node)
            deref->rel_offset.node->last_read = last_read;
    }
    else
    {
        for (i = 0; i < deref->path_len; ++i)
            deref->path[i].node->last_read = last_read;
    }
}
''', '''/* fxc2: see struct hlsl_ir_node.last_use. */
#define LIVENESS_MAX_LOOP_DEPTH 64
static unsigned int liveness_loop_ends[LIVENESS_MAX_LOOP_DEPTH];
static unsigned int liveness_loop_depth;
static bool liveness_loops_too_deep;

static void liveness_note_use(struct hlsl_ir_node *node, unsigned int index)
{
    if (liveness_loop_depth > node->loop_depth && node->loop_depth < LIVENESS_MAX_LOOP_DEPTH)
        index = liveness_loop_ends[node->loop_depth];
    node->last_use = max(node->last_use, index);
}

static void deref_mark_last_read(struct hlsl_deref *deref, unsigned int last_read, unsigned int use_index)
{
    unsigned int i;

    if (hlsl_deref_is_lowered(deref))
    {
        if (deref->rel_offset.node)
        {
            deref->rel_offset.node->last_read = last_read;
            liveness_note_use(deref->rel_offset.node, use_index);
        }
    }
    else
    {
        for (i = 0; i < deref->path_len; ++i)
        {
            deref->path[i].node->last_read = last_read;
            liveness_note_use(deref->path[i].node, use_index);
        }
    }
}
''')
assert "liveness_note_use" in region

rec_start = region.index("static void compute_liveness_recurse(")
head, rec = region[:rec_start], region[rec_start:]
n_before = len(re.findall(r"->last_read = last_read;", rec))
rec = re.sub(r"(\b[\w\.\[\]>-]+?)->last_read = last_read;",
             lambda m: "%s->last_read = last_read, liveness_note_use(%s, instr->index);" % (m.group(1), m.group(1)), rec)
assert n_before >= 15 and "->last_read = last_read;" not in rec, n_before
rec, n_calls = re.subn(r"deref_mark_last_read\(([^;]*?), last_read\);",
                      lambda m: "deref_mark_last_read(%s, last_read, instr->index);" % m.group(1), rec)
assert n_calls >= 5, n_calls

old = '''        const unsigned int last_read = loop_last ? max(instr->index, loop_last) : instr->index;
'''
assert rec.count(old) == 1
rec = rec.replace(old, old + '''
        instr->last_use = 0;
        instr->loop_depth = liveness_loop_depth;
''')

old = '''            if (!var->first_write)
                var->first_write = loop_first ? min(instr->index, loop_first) : instr->index;
'''
assert rec.count(old) == 1
rec = rec.replace(old, old + '''            if (vkd3d_array_reserve((void **)&var->store_indices, &var->store_capacity,
                    var->store_count + 1, sizeof(*var->store_indices)))
                var->store_indices[var->store_count++] = instr->index;
            else
                liveness_loops_too_deep = true;
''')

old = '''            compute_liveness_recurse(&loop->body, loop_first ? loop_first : instr->index,
                    loop_last ? loop_last : loop->next_index);
            compute_liveness_recurse(&loop->iter, loop_first ? loop_first : instr->index,
                    loop_last ? loop_last : loop->next_index);
'''
assert rec.count(old) == 1
rec = rec.replace(old, '''            if (liveness_loop_depth < LIVENESS_MAX_LOOP_DEPTH)
                liveness_loop_ends[liveness_loop_depth] = loop->next_index;
            else
                liveness_loops_too_deep = true;
            ++liveness_loop_depth;
''' + old + '''            --liveness_loop_depth;
''')
s = s[:a] + head + rec + s[b:]

old = '''        LIST_FOR_EACH_ENTRY(var, &scope->vars, struct hlsl_ir_var, scope_entry)
            var->first_write = var->last_read = 0;
    }

    compute_liveness_recurse(body, 0, 0);
'''
assert s.count(old) == 1
s = s.replace(old, '''        LIST_FOR_EACH_ENTRY(var, &scope->vars, struct hlsl_ir_var, scope_entry)
        {
            var->first_write = var->last_read = 0;
            var->store_count = 0;
        }
    }

    liveness_loop_depth = 0;
    liveness_loops_too_deep = false;
    compute_liveness_recurse(body, 0, 0);
''')

# --- decide and allocate ---------------------------------------------------
old = '''static void allocate_temp_registers_recurse(struct hlsl_ctx *ctx, struct hlsl_block *block)
{
    struct hlsl_ir_node *instr;

    LIST_FOR_EACH_ENTRY(instr, &block->instrs, struct hlsl_ir_node, entry)
    {
        /* In SM4 all constants are inlined. */
        if (ctx->profile->major_version >= 4 && instr->type == HLSL_IR_CONSTANT)
            continue;

        allocate_instr_temp_register(ctx, instr);
'''
assert s.count(old) == 1
s = s.replace(old, '''/* fxc2: a load is normally a mov from the variable's register into a fresh
 * temporary, which every use then reads. When the variable is not stored to
 * between the load and the last place its value is needed, the uses can read
 * the variable's register directly and the mov disappears; in code that keeps
 * its state in variables that is a large share of all instructions.
 *
 * "Between" is in terms of liveness indices, which follow program order, so
 * a store in a sibling branch counts as well: conservative, but simple. Loops
 * are covered by last_use, which is the end of the loop when the value was
 * loaded outside a loop it is used in. A store sitting exactly at last_use is
 * the user itself, and reads its operands before it writes. */
static bool load_can_be_elided(struct hlsl_ctx *ctx, const struct hlsl_ir_load *load)
{
    const struct hlsl_ir_node *instr = &load->node;
    const struct hlsl_ir_var *var = load->src.var;
    size_t low = 0, high = var->store_count;

    if (hlsl_version_lt(ctx, 4, 0) || liveness_loops_too_deep || !instr->last_read || !instr->last_use)
        return false;
    if (var->indexable || var->is_uniform || var->is_input_semantic || var->is_output_semantic || var->is_tgsm)
        return false;
    if (instr->data_type->class > HLSL_CLASS_VECTOR || instr->data_type->e.numeric.type == HLSL_TYPE_DOUBLE)
        return false;
    if (!hlsl_deref_is_lowered(&load->src) || load->src.rel_offset.node
            || !hlsl_is_numeric_type(load->src.data_type))
        return false;

    /* First store after the load. */
    while (low < high)
    {
        size_t mid = (low + high) / 2;

        if (var->store_indices[mid] <= instr->index)
            low = mid + 1;
        else
            high = mid;
    }
    return low == var->store_count || var->store_indices[low] >= instr->last_use;
}

static void allocate_temp_registers_recurse(struct hlsl_ctx *ctx, struct hlsl_block *block)
{
    struct hlsl_ir_node *instr;

    LIST_FOR_EACH_ENTRY(instr, &block->instrs, struct hlsl_ir_node, entry)
    {
        /* In SM4 all constants are inlined. */
        if (ctx->profile->major_version >= 4 && instr->type == HLSL_IR_CONSTANT)
            continue;

        if (instr->type == HLSL_IR_LOAD && !instr->reg.allocated && load_can_be_elided(ctx, hlsl_ir_load(instr)))
        {
            struct hlsl_ir_load *load = hlsl_ir_load(instr);

            allocate_variable_temp_register(ctx, load->src.var);
            if (load->src.var->regs[HLSL_REGSET_NUMERIC].allocated)
            {
                instr->reg = hlsl_reg_from_deref(ctx, &load->src);
                instr->reg.writemask = hlsl_combine_writemasks(instr->reg.writemask,
                        vkd3d_write_mask_from_component_count(instr->data_type->e.numeric.dimx));
                instr->reg.type = VSIR_REGISTER_TEMP;
                instr->reg.allocated = true;
                load->elided = true;
                continue;
            }
        }

        allocate_instr_temp_register(ctx, instr);
''')

old = '''    VKD3D_ASSERT(!load->src.var->is_tgsm);
    VKD3D_ASSERT(hlsl_is_numeric_type(type));
    if (type->e.numeric.type == HLSL_TYPE_BOOL && var_is_user_input(version, load->src.var))
'''
assert s.count(old) == 1
s = s.replace(old, '''    if (load->elided)
        return true;

''' + old)
open(path, "w").write(s)

edit("hlsl.c", [
    ('''    vkd3d_free(decl->sroa_fields);
''', '''    vkd3d_free(decl->sroa_fields);
    vkd3d_free(decl->store_indices);
'''),
])
print("patched")
