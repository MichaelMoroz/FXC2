import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


rep('''static bool flatten_conditional_branches(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{''', '''/* fxc2: whether a condition is made of uniforms and constants alone, so that
 * every pixel of a draw takes the branch the same way. */
static bool condition_is_uniform(const struct hlsl_ir_node *node, unsigned int depth)
{
    unsigned int i;

    if (depth > 12)
        return false;
    switch (node->type)
    {
        case HLSL_IR_CONSTANT:
            return true;

        case HLSL_IR_LOAD:
            return hlsl_ir_load(node)->src.var->is_uniform;

        case HLSL_IR_SWIZZLE:
            return condition_is_uniform(hlsl_ir_swizzle(node)->val.node, depth + 1);

        case HLSL_IR_EXPR:
            for (i = 0; i < HLSL_MAX_OPERANDS; ++i)
            {
                const struct hlsl_ir_node *operand = hlsl_ir_expr(node)->operands[i].node;

                if (operand && !condition_is_uniform(operand, depth + 1))
                    return false;
            }
            return true;

        default:
            return false;
    }
}

/* fxc2: "if (_FeatureOn) colour = effect;" is how a material shader switches
 * its features, and as a branch it costs nothing: the GPU takes it the same
 * way for a whole draw and skips what only the effect needed. As a select the
 * effect is computed for every pixel whether it is used or not (Poiyomi's
 * heaviest variants ran 1.5 times FXC's time for 46 such branches). So a
 * branch on uniforms alone is kept; VKD3D_HLSL_FLATTEN_UNIFORM=1 flattens
 * them like any other. */
static bool keep_uniform_branches(void)
{
    static int keep = -1;

    if (keep < 0)
        keep = !hlsl_tuning_enabled("VKD3D_HLSL_FLATTEN_UNIFORM", false);
    return keep;
}

static bool flatten_conditional_branches(struct hlsl_ctx *ctx, struct hlsl_ir_node *instr, void *context)
{''')
rep('''    else if (!is_conditional_block_simple(&iff->then_block) || !is_conditional_block_simple(&iff->else_block))
    {''', '''    else if ((keep_uniform_branches() && condition_is_uniform(iff->condition.node, 0))
            || !is_conditional_block_simple(&iff->then_block) || !is_conditional_block_simple(&iff->else_block))
    {''')
open(p, "w").write(s)

# patch 53's ubfe gained nothing measurable: off unless asked for
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/ir.c")
s = open(p).read()
rep('''    if (program->shader_version.major < 5 || ((env = getenv("VKD3D_UBFE")) && !strcmp(env, "0")))
        return;''', '''    /* Off unless asked for: on ShaderEmu's tick it changed nothing that could be measured. */
    if (program->shader_version.major < 5 || !(env = getenv("VKD3D_UBFE")) || strcmp(env, "1"))
        return;''')
open(p, "w").write(s)
print("patched")
