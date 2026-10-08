import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/preproc.l")
s = open(p).read()

# "A-f" takes in '[', ']', '^', '_' and the backslash: "xr[0x1f]" in a macro's
# last argument was lexed as the integer "0x1f]", the bracket never closed and
# the macro was not expanded ("Identifier is not declared").
old = "<INITIAL,LINE>0[xX][0-9a-fA-f]+{INT_SUFFIX}"
assert s.count(old) == 1
s = s.replace(old, "<INITIAL,LINE>0[xX][0-9a-fA-F]+{INT_SUFFIX}")
open(p, "w").write(s)
print("patched")
