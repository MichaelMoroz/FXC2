#!/usr/bin/env python3
"""Recompiles a directory of sources captured by the DLL (FXC2_DUMP, see the
README) three ways and compares the results:

    opt    fxc2 with its defaults
    plain  fxc2 with the code-generation optimisations switched off
    fxc    Microsoft's compiler, when it is installed

For each source: does it compile, does the D3D11 runtime accept the bytecode,
and how many instructions did each compiler emit.

    python tools/replay.py out/unity_sources [--csv out/unity_replay.csv]
"""
import argparse
import concurrent.futures
import csv
import glob
import os
import re
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from run import FXC2, find_fxc  # noqa: E402
import d3d11  # noqa: E402

PLAIN = {
    "VKD3D_HLSL_SPLIT_STRUCTS": "0", "VKD3D_HLSL_VALUE_NUMBERING": "0", "VKD3D_HLSL_ELIDE_LOADS": "0",
    "VKD3D_HLSL_RETURN_ELSE": "0", "VKD3D_HLSL_RETURN_DUP": "0", "VKD3D_HLSL_RETURN_SWITCH": "0",
    "VKD3D_HLSL_SWITCH": "1", "VKD3D_HLSL_UNROLL_BUDGET": "0", "VKD3D_HLSL_KEEP_ARRAY_BRANCHES": "0",
    "VKD3D_PACK_REGISTERS": "1", "VKD3D_HLSL_SCALAR_MUL": "1", "VKD3D_HLSL_MAD": "0", "VKD3D_HLSL_ADCE": "0", "VKD3D_FORWARD_STORES": "0",
}
NOT_INSTRUCTIONS = ("//", "dcl_", "vs_", "ps_", "gs_", "cs_", "hs_", "ds_")


def count_instructions(blob_path):
    p = subprocess.run([FXC2, "-dumpbin", blob_path], capture_output=True, text=True, errors="replace")
    if p.returncode:
        return None
    return sum(1 for line in p.stdout.splitlines() if line.strip() and not line.lstrip().startswith(NOT_INSTRUCTIONS))


def compile_one(args):
    path, fxc, tmp = args
    name = os.path.basename(path)
    profile = re.sub(r"^\d+_\d+_", "", os.path.splitext(name)[0])
    with open(path, "rb") as f:
        head = f.read(200).decode("latin1")
    entry = re.search(r"// entry: (\S+)", head).group(1)
    flags = int(re.search(r"// flags: (\S+)", head).group(1), 16) if "// flags:" in head else 0x1000
    result = {"source": name, "profile": profile, "entry": entry}

    base = os.path.join(tmp, os.path.splitext(name)[0])
    compat = ["-Gec"] if flags & 0x1000 else []
    for kind, env in (("opt", {}), ("plain", PLAIN)):
        out = "%s.%s.dxbc" % (base, kind)
        e = {k: v for k, v in os.environ.items() if not k.startswith(("VKD3D_HLSL_", "VKD3D_PACK", "VKD3D_FORWARD"))}
        e.update(env)
        p = subprocess.run([FXC2, "-T", profile, "-E", entry, "-Fo", out, path] + compat,
                           capture_output=True, text=True, errors="replace", env=e)
        if p.returncode == 0 and os.path.exists(out):
            result[kind] = count_instructions(out)
            result[kind + "_blob"] = out
        else:
            result[kind] = None
            result[kind + "_error"] = next((l for l in (p.stdout + p.stderr).splitlines() if ": E" in l), "failed")[:160]
    if fxc:
        out = base + ".fxc.dxbc"
        p = subprocess.run([fxc, "/nologo", "/T", profile, "/E", entry, "/Fo", out, path] + (["/Gec"] if compat else []),
                           capture_output=True, text=True, errors="replace")
        result["fxc"] = count_instructions(out) if p.returncode == 0 and os.path.exists(out) else None
    return result


def ratio_summary(label, pairs):
    ratios = [a / b for a, b in pairs if a and b]
    if not ratios:
        return
    better = sum(1 for r in ratios if r < 0.995)
    worse = sum(1 for r in ratios if r > 1.005)
    print("%s: %d shaders, median ratio %.2f, total instructions %d vs %d (%.2f); smaller in %d, equal in %d, "
          "larger in %d" % (label, len(ratios), statistics.median(ratios), sum(a for a, b in pairs if a and b),
                            sum(b for a, b in pairs if a and b),
                            sum(a for a, b in pairs if a and b) / sum(b for a, b in pairs if a and b),
                            better, len(ratios) - better - worse, worse))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory")
    ap.add_argument("--csv")
    ap.add_argument("--no-fxc", action="store_true")
    args = ap.parse_args()

    sources = sorted(glob.glob(os.path.join(args.directory, "*.hlsl")))
    fxc = None if args.no_fxc else find_fxc()
    dev = d3d11.Device()
    with tempfile.TemporaryDirectory(prefix="replay") as tmp:
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            results = list(pool.map(compile_one, [(s, fxc, tmp) for s in sources]))
        rejected = []
        for r in results:
            for kind in ("opt", "plain"):
                blob = r.pop(kind + "_blob", None)
                if blob:
                    hr = dev.check(r["profile"][:2], open(blob, "rb").read())
                    if hr:
                        rejected.append("%s (%s): 0x%08x" % (r["source"], kind, hr))

    print("%d sources" % len(results))
    for kind in ("opt", "plain") + (("fxc",) if fxc else ()):
        print("  %-5s compiled %d" % (kind, sum(1 for r in results if r.get(kind))))
    for r in results:
        for kind in ("opt", "plain"):
            if kind + "_error" in r:
                print("  FAILED %s %s: %s" % (kind, r["source"], r[kind + "_error"]))
    print("  rejected by D3D11: %d" % len(rejected))
    for line in rejected[:10]:
        print("    " + line)

    ratio_summary("optimised vs plain fxc2", [(r.get("opt"), r.get("plain")) for r in results])
    if fxc:
        ratio_summary("optimised fxc2 vs FXC  ", [(r.get("opt"), r.get("fxc")) for r in results])
        ratio_summary("plain fxc2 vs FXC      ", [(r.get("plain"), r.get("fxc")) for r in results])

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["source", "profile", "entry", "opt", "plain", "fxc"], extrasaction="ignore")
            w.writeheader()
            w.writerows(results)
    return 1 if rejected or any(not r.get("opt") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
