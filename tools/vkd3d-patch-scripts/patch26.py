import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(path).read()
old = '''        hlsl_block_add_if(ctx, &chain, cond, &c->body, &tail, HLSL_IF_FORCE_BRANCH, false, &c->loc);
'''
new = '''        /* Left to the usual heuristic: a chain of small cases, such as one
         * that writes one component of a vector each, becomes selects, as it
         * does in FXC's output. */
        hlsl_block_add_if(ctx, &chain, cond, &c->body, &tail,
                hlsl_tuning_enabled("VKD3D_HLSL_SWITCH_BRANCH", false) ? HLSL_IF_FORCE_BRANCH
                : HLSL_IF_FLATTEN_DEFAULT, false, &c->loc);
'''
assert s.count(old) == 1
open(path, "w").write(s.replace(old, new))
print("patched")
