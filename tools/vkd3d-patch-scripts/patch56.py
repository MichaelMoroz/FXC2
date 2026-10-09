import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


rep('''static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{''', '''/* fxc2: the limit for a block that computes in floating point. Material
 * shaders switch their effects with "if (feature) colour = effect;": as a
 * select, everything the effect needed is computed for every pixel, and the
 * driver can no longer leave it out when the feature is off. With the limit of
 * 10 that suits integer code, Poiyomi's heavy variants took 1.11 times FXC's
 * time in the mean and 1.5 times at worst; with 4, 1.01 and 1.05. Integer code
 * (a decoder, an emulator) keeps the other limit: there a branch is the dear
 * thing. VKD3D_HLSL_FLATTEN_FLOAT overrides it. */
static unsigned int flatten_max_float_cost(void)
{
    static int cost = -1;

    if (cost < 0)
    {
        const char *env = getenv("VKD3D_HLSL_FLATTEN_FLOAT");

        cost = env ? atoi(env) : 4;
    }
    return cost;
}

static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{''')
rep('''            case HLSL_IR_EXPR:
                cost += flatten_expr_cost(hlsl_ir_expr(instr));
                break;
''', '''            case HLSL_IR_EXPR:
                cost += flatten_expr_cost(hlsl_ir_expr(instr));
                if (instr->data_type->class <= HLSL_CLASS_MATRIX
                        && (instr->data_type->e.numeric.type == HLSL_TYPE_FLOAT
                        || instr->data_type->e.numeric.type == HLSL_TYPE_HALF
                        || instr->data_type->e.numeric.type == HLSL_TYPE_DOUBLE))
                    has_float = true;
                break;
''')
rep('''    const unsigned int max_cost = flatten_max_cost();
    struct hlsl_ir_node *instr;
    unsigned int cost = 0;
''', '''    const unsigned int max_cost = flatten_max_cost();
    struct hlsl_ir_node *instr;
    unsigned int cost = 0;
    bool has_float = false;
''')
rep('''        if (cost > max_cost)
            return false;
    }

    return true;
}''', '''        if (cost > max_cost || (has_float && cost > flatten_max_float_cost()))
            return false;
    }

    return true;
}''')
open(p, "w").write(s)
print("patched")
