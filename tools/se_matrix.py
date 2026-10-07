#!/usr/bin/env python3
"""Benchmarks ShaderEmu's rvc_harness on fxc2 under several settings of the
tuning environment variables, one line per configuration.

    python tools/se_matrix.py "" "VKD3D_PACK_REGISTERS=0" "VKD3D_PACK_REGISTERS=0 VKD3D_HLSL_ELIDE_LOADS=0"

Each argument is a space separated list of NAME=VALUE ("" = defaults). The
shader cache is cleared for every configuration, so each one is a fresh
compile. `--which fxc|dxc` benchmarks the reference compilers instead.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SE = os.path.join(ROOT, "out", "ShaderEmu")


def bench(which, config, runs, frames):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VKD3D_HLSL_", "VKD3D_PACK", "VKD3D_SCALAR"))}
    for pair in config.split():
        key, value = pair.split("=", 1)
        env[key] = value

    cache = os.path.join("build", "cache_" + which)
    exe = os.path.join("bin", "rvc_harness.exe")
    if which == "fxc2":
        os.makedirs(os.path.join(SE, "bin_fxc2"), exist_ok=True)
        shutil.copy(os.path.join(SE, exe), os.path.join(SE, "bin_fxc2"))
        shutil.copy(os.path.join(ROOT, "bin", "d3dcompiler_47.dll"), os.path.join(SE, "bin_fxc2"))
        exe = os.path.join("bin_fxc2", "rvc_harness.exe")
        shutil.rmtree(os.path.join(SE, cache), ignore_errors=True)

    cmd = [os.path.join(SE, exe), "--dxc" if which == "dxc" else "--d3d11", "--rvc", r"experiments\rvc_opt",
           "--payload", r"rvc\_Nix\rvc\data-net", "--no-stdin", "--fixed-dt", "0.004", "--ticks", "2048",
           "--frames", str(frames), "--bench", "100", "--cache", cache]
    if which == "dxc":
        cmd.append("--no-bands")

    ips, text = [], ""
    for _ in range(runs):
        p = subprocess.run(cmd, cwd=SE, env=env, capture_output=True, text=True, errors="replace")
        text = p.stdout + p.stderr
        m = re.search(r"ips=(\d+).*state=(\w+)", text)
        if not m:
            return None, text
        ips.append(int(m.group(1)))
        state = m.group(2)
        if not hasattr(bench, "info") or "compiled in" in text:
            c = re.search(r"CPUTick' fragment: compiled in ([\d.]+)s \((\d+) bytes\)", text)
            bench.info = c.groups() if c else bench.__dict__.get("info", ("-", "-"))
    return (max(ips), state) + tuple(bench.info), text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("configs", nargs="*", default=[""])
    ap.add_argument("--which", default="fxc2", choices=["fxc", "fxc2", "dxc"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--frames", type=int, default=6000)
    args = ap.parse_args()
    for config in args.configs:
        result, text = bench(args.which, config, args.runs, args.frames)
        label = "%s [%s]" % (args.which, config)
        if result is None:
            print("%-78s FAILED\n%s" % (label, "\n".join(text.strip().splitlines()[-4:])))
            continue
        ips, state, seconds, size = result
        print("%-78s %5dk IPS  state=%s  %s bytes  compile %ss" % (label, ips // 1000, state, size, seconds))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
