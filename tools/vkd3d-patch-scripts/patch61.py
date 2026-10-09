import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.y")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


rep('''        LIST_FOR_EACH_ENTRY(node, &block->instrs, struct hlsl_ir_node, entry)
        {
            if (node->type != HLSL_IR_CONSTANT && node->type != HLSL_IR_EXPR && node->type != HLSL_IR_SWIZZLE)
                reads_variable = true;
        }
''', '''        /* The temporaries of the expression itself are stored to in the
         * expression: the initialiser of each component of a variable loads
         * one, and each cloned every static initialiser there was (190 times
         * in a Poiyomi variant, a third of the time of compiling it). */
        LIST_FOR_EACH_ENTRY(node, &block->instrs, struct hlsl_ir_node, entry)
        {
            if (node->type == HLSL_IR_LOAD && !hlsl_ir_load(node)->src.var->is_synthetic)
                reads_variable = true;
        }
''')
open(p, "w").write(s)
print("patched")
