import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.y")
s = open(path).read()
old = '''    if (!hlsl_clone_block(ctx, &expr, &ctx->static_initializers))
        return ret;
    hlsl_block_add_block(&expr, block);
'''
new = '''    /* fxc2: the initialisers of every static variable are only needed when
     * the expression reads a variable. Cloning and folding them for each case
     * label and array size made parsing a large shader take tens of seconds. */
    {
        bool reads_variable = false;

        LIST_FOR_EACH_ENTRY(node, &block->instrs, struct hlsl_ir_node, entry)
        {
            if (node->type != HLSL_IR_CONSTANT && node->type != HLSL_IR_EXPR && node->type != HLSL_IR_SWIZZLE)
                reads_variable = true;
        }

        if (!reads_variable)
            hlsl_block_init(&expr);
        else if (!hlsl_clone_block(ctx, &expr, &ctx->static_initializers))
            return ret;
    }
    hlsl_block_add_block(&expr, block);
'''
assert s.count(old) == 1
open(path, "w").write(s.replace(old, new))
print("patched")
