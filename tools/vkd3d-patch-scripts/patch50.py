import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


# A call that was inlined leaves a load of its return value behind even when
# the caller reads the value again for its test; nothing uses it, and it stood
# between the branch and the test.
rep('''            if (between == iff->condition.node || between == first)
                continue;
            prev = between;
            break;
''', '''            if (between == iff->condition.node || between == first)
                continue;
            if (list_empty(&between->uses) && (between->type == HLSL_IR_LOAD || between->type == HLSL_IR_CONSTANT
                    || between->type == HLSL_IR_EXPR || between->type == HLSL_IR_SWIZZLE))
                continue;
            prev = between;
            break;
''')
open(p, "w").write(s)
print("patched")
