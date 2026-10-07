import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


rep('''static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{''', '''/* fxc2: whether a deref indexes an array with a run-time value, which means
 * the variable lives in memory (an indexable temp) rather than in registers. */
static bool deref_has_dynamic_index(const struct hlsl_deref *deref)
{
    unsigned int i;

    for (i = 0; i < deref->path_len; ++i)
    {
        if (deref->path[i].node->type != HLSL_IR_CONSTANT)
            return true;
    }
    return false;
}

static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{''')

rep('''            case HLSL_IR_STORE:
                if (hlsl_ir_store(instr)->lhs.var->is_tgsm)
                    return false;
                ++cost;
                break;

            case HLSL_IR_LOAD:
                if (hlsl_ir_load(instr)->src.var->is_tgsm)
                    return false;
                break;
''', '''            case HLSL_IR_STORE:
                if (hlsl_ir_store(instr)->lhs.var->is_tgsm)
                    return false;
                /* fxc2: flattening "if (c) a[i] = x;" makes it an
                 * unconditional read, select and write of memory, which is
                 * far more expensive than the branch it replaces. */
                if (deref_has_dynamic_index(&hlsl_ir_store(instr)->lhs)
                        && hlsl_tuning_enabled("VKD3D_HLSL_KEEP_ARRAY_BRANCHES", true))
                    return false;
                ++cost;
                break;

            case HLSL_IR_LOAD:
                if (hlsl_ir_load(instr)->src.var->is_tgsm)
                    return false;
                if (deref_has_dynamic_index(&hlsl_ir_load(instr)->src)
                        && hlsl_tuning_enabled("VKD3D_HLSL_KEEP_ARRAY_BRANCHES", true))
                    return false;
                break;
''')
open(path, "w").write(s)
print("patched")
