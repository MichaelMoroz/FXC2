#!/usr/bin/env python3
"""Benchmarks ShaderEmu's rvc_harness under several settings of the vkd3d
tuning environment variables, one line per configuration.

    python tools/se_matrix.py "" "VKD3D_PACK_REGISTERS=1" "VKD3D_HLSL_ELIDE_LOADS=0"
    python tools/se_matrix.py --which fxc ""
    python tools/se_matrix.py --which dxc ""

Each argument is a space separated list of NAME=VALUE ("" = defaults). For
fxc2 the shader cache is cleared for every configuration, so each one is a
fresh compile.

What is measured is the whole frame in the harness's --bench mode (fixed
time step, GPU drained at both ends; repeat runs agree to about 0.3%), at
2048 and at 2 emulated instructions a frame:

    IPS     emulated instructions per second at 2048 a frame, best of the runs
    fixed   ms a frame costs whatever it emulates (state in and out, array
            setup, the commit and device passes)
    per     ns per emulated instruction on top of that

The state hash must be the same for every compiler and setting.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SE = os.path.join(ROOT, "out", "ShaderEmu")
TUNING_PREFIXES = ("VKD3D_HLSL_", "VKD3D_PACK", "VKD3D_REGISTER", "VKD3D_SCALAR")


def harness(which, env, extra):
    cache = os.path.join("build", "cache_" + which)
    exe = os.path.join("bin_fxc2" if which == "fxc2" else "bin", "rvc_harness.exe")
    cmd = [os.path.join(SE, exe), "--dxc" if which == "dxc" else "--d3d11", "--rvc", r"experiments\rvc_opt",
           "--payload", r"rvc\_Nix\rvc\data-net", "--no-stdin", "--fixed-dt", "0.004", "--cache", cache]
    if which == "dxc":
        cmd.append("--no-bands")
    p = subprocess.run(cmd + extra, cwd=SE, env=env, capture_output=True, text=True, errors="replace")
    return p.stdout + p.stderr


def bench(which, config, runs):
    env = {k: v for k, v in os.environ.items() if not k.startswith(TUNING_PREFIXES)}
    for pair in config.split():
        key, value = pair.split("=", 1)
        env[key] = value

    if which == "fxc2":
        os.makedirs(os.path.join(SE, "bin_fxc2"), exist_ok=True)
        shutil.copy(os.path.join(SE, "bin", "rvc_harness.exe"), os.path.join(SE, "bin_fxc2"))
        shutil.copy(os.path.join(ROOT, "bin", "d3dcompiler_47.dll"), os.path.join(SE, "bin_fxc2"))
        shutil.rmtree(os.path.join(SE, "build", "cache_fxc2"), ignore_errors=True)

    compiled, state, frame_ms, per_frame, ips = "", None, {}, {}, 0
    for ticks, frames in ((2048, 6000), (2, 9000)):
        best = None
        for _ in range(runs):
            text = harness(which, env, ["--ticks", str(ticks), "--frames", str(frames), "--bench", "100"])
            m = re.search(r"BENCH frames=(\d+) seconds=([\d.]+) instructions=\d+ ips=(\d+) fps=[\d.]+ "
                          r"per_frame=([\d.]+) state=(\w+)", text)
            if not m:
                return None, text
            c = re.search(r"CPUTick' fragment: compiled in ([\d.]+)s \((\d+) bytes\)", text)
            if c:
                compiled = "%ss %s bytes" % c.groups()
            ms = float(m.group(2)) * 1000.0 / int(m.group(1))
            if best is None or ms < best:
                best = ms
                per_frame[ticks] = float(m.group(4))
                if ticks == 2048:
                    ips, state = int(m.group(3)), m.group(5)
        frame_ms[ticks] = best
    per_instruction = (frame_ms[2048] - frame_ms[2]) * 1e6 / (per_frame[2048] - per_frame[2])
    return (ips, frame_ms[2], per_instruction, state, compiled), text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("configs", nargs="*", default=[""])
    ap.add_argument("--which", default="fxc2", choices=["fxc", "fxc2", "dxc"])
    ap.add_argument("--runs", type=int, default=2, help="runs per measurement; the best one counts")
    args = ap.parse_args()
    for config in args.configs:
        result, text = bench(args.which, config, args.runs)
        label = "%s [%s]" % (args.which, config)
        if result is None:
            print("%-66s FAILED\n%s" % (label, "\n".join(text.strip().splitlines()[-4:])))
            continue
        ips, fixed, per_instruction, state, compiled = result
        print("%-62s %5dk IPS  fixed %.3f ms  per %5.1f ns  state=%s  %s" % (
            label, ips // 1000, fixed, per_instruction, state, compiled))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
