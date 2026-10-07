import os
import re
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")
# "4294967296.0l": the l suffix makes a literal a double for FXC. The preprocessor cut it off
# as a token of its own ("4294967296.0 l", a syntax error) and the compiler did not know it.
# It is accepted now; the value is still held in single precision.
p = base + "preproc.l"
s = open(p).read()
lines = s.split("\n")
changed = 0
for i, line in enumerate(lines):
    if line.startswith("<INITIAL>[0-9]") and "[hHfF]" in line and "return T_TEXT" in line:
        lines[i] = line.replace("[hHfF]", "[hHfFlL]")
        changed += 1
assert changed == 3, changed
open(p, "w").write("\n".join(lines))
p = base + "hlsl.l"
s = open(p).read()
assert s.count("[h|H|f|F]?") == 3
s = s.replace("[h|H|f|F]?", "[h|H|f|F|l|L]?")
open(p, "w").write(s)
print("patched")
