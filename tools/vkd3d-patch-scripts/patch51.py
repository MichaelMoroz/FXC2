import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


# FXC sets refactoringAllowed unless it was asked for IEEE strictness, and a
# driver's compiler may read it as leave to reorder floating point. (Declaring
# an array of scalars one component wide, as FXC also does, was tried with it
# and is slower: 0.343 ms against 0.331 for ShaderEmu's tick on D3D12.)
rep('''    generate_vsir_scan_required_features(ctx, program);
    generate_vsir_scan_global_flags(ctx, program, func);

    program->ssa_count = ctx->ssa_count;
''', '''    generate_vsir_scan_required_features(ctx, program);
    generate_vsir_scan_global_flags(ctx, program, func);
    {
        const char *env = getenv("VKD3D_HLSL_IEEE_STRICT");

        if (!(env && !strcmp(env, "1")))
            program->global_flags |= VKD3DSGF_REFACTORING_ALLOWED;
    }

    program->ssa_count = ctx->ssa_count;
''')
open(p, "w").write(s)
print("patched")
