import os
path = os.path.expanduser("~/fxc2/vkd3d/include/private/vkd3d_common.h")
s = open(path).read()
old = '''#define TRACE_(ch, args...) do { } while (0)
'''
new = '''/* fxc2: channel traces are written TRACE_(channel)(format, ...), which the
 * two-argument form upstream has here does not expand; a build with
 * VKD3D_NO_TRACE_MESSAGES did not compile. */
#define TRACE_(ch) while (0) vkd3d_dbg_printf_noop
static inline void vkd3d_dbg_printf_noop(const char *format, ...)
{
}
'''
assert s.count(old) == 1
open(path, "w").write(s.replace(old, new))
print("patched")
