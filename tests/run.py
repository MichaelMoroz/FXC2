"""Compiles every shader in tests/shaders with fxc2 and checks the result.

Checks, per shader:
  * fxc2 compiles it (and how long that takes);
  * the D3D11 runtime accepts the DXBC (CreateXxxShader on WARP), SM4+ only;
  * for shaders with a `// render: <floats>` line, a fullscreen draw matches
    the same shader compiled by fxc.exe pixel for pixel (within a tolerance).

fxc.exe is used purely as the reference; tests still run without it, minus
the comparison columns.

Usage: python tests/run.py [--pipeline NAME] [--keep] [filter]
"""
import argparse
import glob
import os
import re
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import d3d11  # noqa: E402

FXC2 = os.path.join(ROOT, "bin", "fxc2.exe")
FULLSCREEN_VS = """
float4 main(uint id : SV_VertexID) : SV_Position
{
    return float4((id << 1 & 2) * 2.0 - 1.0, (id & 2) * -2.0 + 1.0, 0.0, 1.0);
}
"""
TOLERANCE = 2e-3


def find_fxc():
    kits = r"C:\Program Files (x86)\Windows Kits\10\bin"
    found = sorted(glob.glob(os.path.join(kits, "10.*", "x64", "fxc.exe")))
    return found[-1] if found else None


def run(cmd):
    start = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip(), time.perf_counter() - start


def directives(path):
    d = {}
    with open(path) as f:
        for line in f:
            m = re.match(r"//\s*(\w+):\s*(.*)", line)
            if not m:
                break
            d[m.group(1)] = m.group(2).strip()
    return d


def instruction_count(blob_path):
    rc, text, _ = run([FXC2, "-dumpbin", blob_path])
    if rc:
        return None
    return sum(1 for l in text.splitlines()
               if l.strip() and not l.lstrip().startswith(("//", "dcl_", "vs_", "ps_", "gs_", "cs_", "hs_", "ds_")))


def compile_fxc2(src, profile, out, pipeline):
    if pipeline == "direct":
        return run([FXC2, "-T", profile, "-E", "main", "-Fo", out, src])
    return run([sys.executable, os.path.join(ROOT, "tools", "hlsl2dxbc.py"), "--via", pipeline,
                "-T", profile, "-E", "main", "-Fo", out, src])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("filter", nargs="?", default="")
    ap.add_argument("--pipeline", default="direct", help="direct (default), slang, dxc or auto")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    fxc = find_fxc()
    dev = d3d11.Device()

    vs_src = os.path.join(OUT, "_fullscreen_vs.hlsl")
    vs_obj = os.path.join(OUT, "_fullscreen_vs.dxbc")
    with open(vs_src, "w") as f:
        f.write(FULLSCREEN_VS)
    rc, msg, _ = run([FXC2, "-T", "vs_4_0", "-Fo", vs_obj, vs_src])
    assert rc == 0, msg
    vs_blob = open(vs_obj, "rb").read()

    print("%-18s %-7s | %-8s %8s %6s %5s | %8s %6s %5s | %-8s %s" % (
        "shader", "profile", "fxc2", "time", "bytes", "insns", "fxc time", "bytes", "insns", "d3d11", "render vs fxc"))
    failures = 0
    for src in sorted(glob.glob(os.path.join(HERE, "shaders", "*.hlsl"))):
        name = os.path.splitext(os.path.basename(src))[0]
        if args.filter not in name:
            continue
        d = directives(src)
        profile = d["profile"]
        stage, major = profile[:2], int(profile[3])
        ours = os.path.join(OUT, name + ".fxc2.dxbc")
        ref = os.path.join(OUT, name + ".fxc.dxbc")
        for p in (ours, ref):
            if os.path.exists(p):
                os.remove(p)

        rc, msg, t_ours = compile_fxc2(src, profile, ours, args.pipeline)
        ok = rc == 0 and os.path.exists(ours)
        ref_ok, t_ref = False, 0.0
        if fxc:
            rrc, _, t_ref = run([fxc, "/nologo", "/T", profile, "/E", "main", "/Fo", ref, src])
            ref_ok = rrc == 0

        cols = ["%-18s %-7s" % (name, profile)]
        if ok:
            cols.append("%-8s %7.2fs %6d %5s" % ("ok", t_ours, os.path.getsize(ours), instruction_count(ours)))
        else:
            cols.append("%-8s %7.2fs %6s %5s" % ("FAIL", t_ours, "-", "-"))
        if ref_ok:
            cols.append("%7.2fs %6d %5s" % (t_ref, os.path.getsize(ref), instruction_count(ref)))
        else:
            cols.append("%8s %6s %5s" % ("-", "-", "-"))

        status, render = "-", ""
        if ok and major >= 4:
            hr = dev.check(stage, open(ours, "rb").read())
            status = "ok" if hr == 0 else "0x%08x" % hr
            ok = ok and hr == 0
        if ok and ref_ok and "render" in d:
            cb = struct.pack("%df" % len(d["render"].split()), *map(float, d["render"].split()))
            a = dev.render(vs_blob, open(ours, "rb").read(), cb)
            b = dev.render(vs_blob, open(ref, "rb").read(), cb)
            worst = max(abs(x - y) if x == x or y == y else 0.0 for x, y in zip(a, b))
            bad = sum(1 for x, y in zip(a, b) if abs(x - y) > TOLERANCE)
            render = "max diff %.2g" % worst + ("" if not bad else "  MISMATCH in %d/%d values" % (bad, len(a)))
            ok = ok and not bad
        cols.append("%-8s %s" % (status, render))
        print(" | ".join(cols))
        if not ok:
            failures += 1
            for line in msg.splitlines()[:4]:
                print("      " + line)
    print("\n%d failure(s)" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
