"""Compile-time and (WARP) run-time comparison of fxc2 against fxc.exe.

Usage: python tests/bench.py [--gpu]
"""
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from run import FXC2, FULLSCREEN_VS, find_fxc, instruction_count, run  # noqa: E402
import d3d11  # noqa: E402

OUT = os.path.join(ROOT, "out", "bench")

# Blur kernel: gradient samples in nested constant loops, which both compilers
# must unroll (KxK texture samples).
BLUR = """
Texture2D t; SamplerState s;
cbuffer C { float2 resolution; float k; float pad; };
float4 main(float4 p : SV_Position) : SV_Target
{
    float4 acc = 0;
    for (int y = -R; y <= R; ++y)
        for (int x = -R; x <= R; ++x)
            acc += t.Sample(s, (p.xy + float2(x, y)) / resolution) * exp(-(x * x + y * y) * k);
    return acc;
}
"""


def generated_big(n):
    """n small functions calling each other, each with a loop and a branch."""
    parts = ["cbuffer C { float2 resolution; float k; float pad; };",
             "float f0(float2 p) { return sin(p.x) * cos(p.y); }"]
    for i in range(1, n):
        parts.append(
            "float f%d(float2 p) { float a = 0; for (int i = 0; i < %d; ++i) { p = p.yx * 1.1 + %f; "
            "if (p.x > p.y) a += f%d(p); else a -= f%d(p * 0.5); } return a; }"
            % (i, 2 + i % 3, i * 0.01, i - 1, max(i - 2, 0)))
    parts.append("float4 main(float4 p : SV_Position) : SV_Target { float2 uv = p.xy / resolution; "
                 "return float4(f%d(uv), f%d(uv.yx), k, 1); }" % (n - 1, n - 2))
    return "\n".join(parts)


def best_of(cmd, n=3):
    best, rc, msg = 1e9, 0, ""
    for _ in range(n):
        rc, msg, t = run(cmd)
        best = min(best, t)
        if t > 20:
            break
    return rc, msg, best


def main():
    os.makedirs(OUT, exist_ok=True)
    fxc = find_fxc()
    cases = [("raymarch_ps", open(os.path.join(HERE, "shaders", "raymarch_ps.hlsl")).read()),
             ("matrix_ps", open(os.path.join(HERE, "shaders", "matrix_ps.hlsl")).read())]
    cases += [("blur %dx%d" % (2 * r + 1, 2 * r + 1), "#define R %d\n" % r + BLUR) for r in (3, 8, 15)]
    cases += [("call chain x%d" % n, generated_big(n)) for n in (8, 12)]

    print("compile time (best of 3)\n")
    print("| shader | fxc2 time | fxc time | speedup | fxc2 insns | fxc insns |")
    print("|---|---|---|---|---|---|")
    built = {}
    for name, source in cases:
        base = os.path.join(OUT, name.replace(" ", "_"))
        with open(base + ".hlsl", "w") as f:
            f.write(source)
        rc, msg, t_ours = best_of([FXC2, "-T", "ps_5_0", "-Fo", base + ".fxc2.dxbc", base + ".hlsl"])
        ours = "%.2fs" % t_ours if rc == 0 else "FAIL"
        theirs, speed, ref_insns = "-", "-", "-"
        if fxc:
            rrc, rmsg, t_ref = best_of([fxc, "/nologo", "/T", "ps_5_0", "/Fo", base + ".fxc.dxbc", base + ".hlsl"])
            theirs = "%.2fs" % t_ref if rrc == 0 else "FAIL"
            if rc == 0 and rrc == 0:
                speed = "%.1fx" % (t_ref / t_ours)
                ref_insns = instruction_count(base + ".fxc.dxbc")
                built[name] = base
        print("| %s | %s | %s | %s | %s | %s |" % (
            name, ours, theirs, speed, instruction_count(base + ".fxc2.dxbc") if rc == 0 else "-", ref_insns))

    if not built:
        return
    gpu = "--gpu" in sys.argv
    size = 2048 if gpu else 512
    print("\nrun time on %s, %dx%d fullscreen draw, best of 5\n" % (
        "the hardware GPU" if gpu else "WARP (CPU rasteriser)", size, size))
    print("| shader | fxc2 code | fxc code | ratio |")
    print("|---|---|---|---|")
    dev = d3d11.Device(hardware=gpu)
    vs_src = os.path.join(OUT, "_vs.hlsl")
    with open(vs_src, "w") as f:
        f.write(FULLSCREEN_VS)
    assert run([FXC2, "-T", "vs_4_0", "-Fo", vs_src + ".dxbc", vs_src])[0] == 0
    vs = open(vs_src + ".dxbc", "rb").read()
    cb = struct.pack("4f", size, size, 0.5, 0)
    for name, base in built.items():
        times = []
        for kind in ("fxc2", "fxc"):
            blob = open("%s.%s.dxbc" % (base, kind), "rb").read()
            dev.render(vs, blob, cb, size, size, readback=False)   # warm up WARP's JIT
            best = 1e9
            for _ in range(5):
                start = time.perf_counter()
                dev.render(vs, blob, cb, size, size, readback=False)
                best = min(best, time.perf_counter() - start)
            times.append(best)
        print("| %s | %.1f ms | %.1f ms | %.2fx |" % (name, times[0] * 1e3, times[1] * 1e3, times[0] / times[1]))


if __name__ == "__main__":
    main()
