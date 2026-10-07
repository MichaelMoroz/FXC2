import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()
a = """    /* fxc2: again, now that structures are separate variables. Removing dead
     * code makes small branches flattenable that were not before; put the
     * component stores in them together first, or each component is selected
     * separately. */
    if (hlsl_version_ge(ctx, 4, 0) && hlsl_tuning_enabled("VKD3D_HLSL_ADCE", true)
            && adce_execute(ctx, body))
    {
        vectorize_stores(ctx, body);
        hlsl_run_const_passes(ctx, body);
    }
"""
assert s.count(a) == 1
s = s.replace(a, """    /* fxc2: again, now that structures are separate variables. The constant
     * passes are not run here: they flatten branches, and a branch that has
     * just become small enough for that still stores its vectors a component
     * at a time, each of which would become a select. (Putting those stores
     * together first is not possible yet: vectorize_stores() is only right
     * where it runs later on. Doing it here moved stores across loads and
     * broke the collider shaders of a Unity project.) */
    if (hlsl_version_ge(ctx, 4, 0) && hlsl_tuning_enabled("VKD3D_HLSL_ADCE", true))
        adce_execute(ctx, body);
""")
open(p, "w").write(s)
print("patched")
