import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.y")
s = open(p).read()
a = '''        else if (!strcmp(attr->name, "fastopt")
                || !strcmp(attr->name, "allow_uav_condition"))
        {
            hlsl_fixme(ctx, loc, "Unhandled attribute '%s'.", attr->name);
        }
'''
assert s.count(a) == 1
s = s.replace(a, '''        else if (!strcmp(attr->name, "fastopt")
                || !strcmp(attr->name, "allow_uav_condition"))
        {
            /* fxc2: both only tell FXC's optimiser what it may do or skip
             * ([fastopt]: do not spend time on this loop; the other allows a
             * loop condition that depends on a UAV read). Nothing here needs
             * telling. Poiyomi's shaders use [fastopt]. */
        }
''')
open(p, "w").write(s)
print("patched")
