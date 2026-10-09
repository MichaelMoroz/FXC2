#!/usr/bin/env python3
"""How fast do the shaders run? Compiles captured shader sources with FXC and
with fxc2 and times both builds on the GPU, outside the application they came
from: no editor to restart, a few hundred shaders in a few minutes.

    tools\\shaderbench\\build.bat                      (once: the harness, needs MSVC)
    python tools/shaderbench.py out/unity_sources out/poiyomi_sources --csv out/shaderbench.csv

The sources are what the DLL saves with %TEMP%\\fxc2.dump.on (see the README):
one file per D3DCompile call, named <pid>_<n>_<profile>.hlsl, with the entry
point and the flags on its first lines.

What is measured, per shader and per build:

  pixel shaders   ns per pixel: a full-screen triangle on a 1024 x 1024 target,
                  drawn often enough to take about 25 ms, fastest of five runs
  vertex shaders  ns per vertex: 65,536 points a draw, almost all clipped

Both include what any shader costs there (rasterising, writing the target,
clipping); the "floor" lines are that cost alone, measured with a shader that
does nothing. A shader near the floor cannot show a difference between builds,
so the summary is given twice: for all shaders and for those that cost at
least three times the floor.

and for pixel shaders whether the builds computed the same picture. Inputs are
made up from each shader's reflection data (tools/shaderbench/shaderbench.cpp):
the same values for every build, but not the application's. A branch on a
material property is taken or not by the luck of that property's made-up value,
and a loop bounded by one runs one to three times. So this compares builds of
one shader on one path through it; it does not say what a frame costs.

Builds: "fxc" is FXC with its optimiser, "fxc2" is fxc2. Sources whose flags
ask FXC to skip optimisation (Unity passes that for shaders with "#pragma
skip_optimizations", which unlocked Poiyomi shaders have) get a third,
"fxc-od", which is what the stock editor would run for them.
"""
import argparse
import concurrent.futures
import csv
import glob
import hashlib
import math
import os
import re
import statistics
import struct
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from run import FXC2, find_fxc  # noqa: E402

WORK = os.path.join(ROOT, "out", "shaderbench")
CACHE = os.path.join(WORK, "cache")
EXE = os.path.join(WORK, "shaderbench.exe")
SKIP_OPTIMIZATION = 0x4
BACKWARDS_COMPATIBILITY = 0x1000


# ---- compiling ---------------------------------------------------------------------------

def tool_stamp(path):
    st = os.stat(path)
    return "%s|%d|%d" % (os.path.basename(path), st.st_size, int(st.st_mtime))


_locks, _locks_guard = {}, threading.Lock()


def compile_cached(build, fxc, source_bytes, profile, entry, compat, source_path=None):
    """Returns the path of the bytecode, or None when the compiler refused."""
    tool = FXC2 if build == "fxc2" else fxc
    key = hashlib.sha1(b"|".join([source_bytes, build.encode(), profile.encode(), entry.encode(),
                                  b"1" if compat else b"0", tool_stamp(tool).encode(),
                                  os.environ.get("SHADERBENCH_VARIANT", "").encode()])).hexdigest()
    out = os.path.join(CACHE, key + ".dxbc")
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:   # two sources often need the same vertex shader
        return _compile(build, fxc, source_bytes, profile, entry, compat, source_path, key, out)


def _compile(build, fxc, source_bytes, profile, entry, compat, source_path, key, out):
    if os.path.exists(out):
        return out
    if os.path.exists(out + ".failed"):
        return None
    if source_path is None:
        source_path = os.path.join(CACHE, "%s_%d.hlsl" % (key, threading.get_ident()))
        with open(source_path, "wb") as f:
            f.write(source_bytes)
    tmp = out + ".tmp%d_%d" % (os.getpid(), threading.get_ident())   # two threads may want the same vertex shader
    if build == "fxc2":
        cmd = [FXC2, "-T", profile, "-E", entry, "-Fo", tmp, source_path] + (["-Gec"] if compat else [])
    else:
        cmd = [fxc, "/nologo", "/T", profile, "/E", entry, "/Fo", tmp, source_path] + (["/Gec"] if compat else [])
        if build == "fxc-od":
            cmd.append("/Od")
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode == 0 and os.path.exists(tmp):
        try:
            os.replace(tmp, out)
        except OSError:
            # another thread got there first with the same thing
            if not os.path.exists(out):
                raise
            os.remove(tmp)
        return out
    with open(out + ".failed", "w") as f:
        f.write(p.stdout + p.stderr)
    return None


# ---- signatures --------------------------------------------------------------------------

def chunks(blob):
    if blob[:4] != b"DXBC":
        return {}
    count = struct.unpack_from("<I", blob, 28)[0]
    found = {}
    for i in range(count):
        offset = struct.unpack_from("<I", blob, 32 + 4 * i)[0]
        tag = blob[offset:offset + 4].decode("latin1")
        size = struct.unpack_from("<I", blob, offset + 4)[0]
        found.setdefault(tag, blob[offset + 8:offset + 8 + size])
    return found


def signature(blob, output):
    """[(semantic, index, system value, component type, register, mask)] in the order declared."""
    found = chunks(blob)
    for tag, element, skip in (("OSGN", 24, 0), ("OSG5", 28, 4), ("OSG1", 32, 4)) if output else (("ISGN", 24, 0), ("ISG1", 32, 4)):
        data = found.get(tag)
        if data is None:
            continue
        count = struct.unpack_from("<I", data, 0)[0]
        result = []
        for i in range(count):
            name, index, sysval, comp, register, mask = struct.unpack_from("<IIIIIB", data, 8 + i * element + skip)
            end = data.index(b"\0", name)
            result.append((data[name:end].decode("latin1"), index, sysval, comp, register, mask))
        return result
    return []


# what a vertex shader cannot hand to a pixel shader: primitive id, front face, sample index
NOT_FROM_VERTEX_SHADER = {7, 9, 10}
COMPONENT_TYPES = {1: "uint", 2: "int", 3: "float"}


def companion_vertex_shader(ps_inputs):
    """Source of a vertex shader that draws one screen-filling triangle and outputs what the
    pixel shader takes in, in the same order, so that the same compiler lays it out the same."""
    fields, body = [], []
    for n, (name, index, sysval, comp, register, mask) in enumerate(ps_inputs):
        if sysval in NOT_FROM_VERTEX_SHADER or register == 0xffffffff:
            continue
        count = bin(mask & 15).count("1") or 1
        if sysval == 1:
            fields.append("    float4 f%d : SV_Position;" % n)
            body.append("    o.f%d = pos;" % n)
            continue
        base = COMPONENT_TYPES.get(comp, "float")
        kind = base + (str(count) if count > 1 else "")
        fields.append("    %s f%d : %s%d;" % (kind, n, name, index))
        if base == "float":
            scale = 1.0 + 0.1 * (index % 8)
            body.append("    o.f%d = (%s)(float4(uv.x, uv.y, 0.5, 1.0) * %.2f);" % (n, kind, scale))
        else:
            body.append("    o.f%d = (%s)1;" % (n, kind))
    return ("struct O\n{\n%s\n};\nO main(uint id : SV_VertexID)\n{\n    O o;\n"
            "    float2 uv = float2((id << 1) & 2, id & 2);\n"
            "    float4 pos = float4(uv * float2(2, -2) + float2(-1, 1), 0.5, 1);\n%s\n    return o;\n}\n"
            % ("\n".join(fields) if fields else "    float4 pos : SV_Position;",
               "\n".join(body) if fields else "    o.pos = pos;"))


def signatures_agree(ps_inputs, vs_outputs):
    produced = {(name.upper(), index): (register, mask) for name, index, sysval, comp, register, mask in vs_outputs}
    for name, index, sysval, comp, register, mask in ps_inputs:
        if sysval in NOT_FROM_VERTEX_SHADER or register == 0xffffffff:
            continue
        got = produced.get((name.upper(), index))
        if got is None or got[0] != register or (got[1] & mask) != mask:
            return False
    return True


# ---- one source --------------------------------------------------------------------------

def prepare(args):
    path, fxc = args
    name = os.path.basename(path)
    profile = re.sub(r"^\d+_\d+_", "", os.path.splitext(name)[0])
    with open(path, "rb") as f:
        source = f.read()
    head = source[:300].decode("latin1")
    entry = re.search(r"// entry: (\S+)", head)
    flags = re.search(r"// flags: (\S+)", head)
    entry = entry.group(1) if entry else "main"
    flags = int(flags.group(1), 16) if flags else BACKWARDS_COMPATIBILITY
    compat = bool(flags & BACKWARDS_COMPATIBILITY)
    stage = profile[:2]
    item = {"source": name, "dir": os.path.basename(os.path.dirname(path)), "profile": profile, "stage": stage,
            "builds": [], "notes": {}}
    if stage not in ("ps", "vs"):
        return item
    wanted = ["fxc", "fxc2"] + (["fxc-od"] if flags & SKIP_OPTIMIZATION else [])
    for build in wanted:
        blob_path = compile_cached(build, fxc, source, profile, entry, compat, path)
        if not blob_path:
            item["notes"][build] = "does not compile"
            continue
        aux = "-"
        if stage == "ps":
            with open(blob_path, "rb") as f:
                inputs = signature(f.read(), False)
            vs_source = companion_vertex_shader(inputs).encode()
            vs_profile = "vs_4_0" if profile.startswith("ps_4") else "vs_5_0"
            aux = compile_cached("fxc2" if build == "fxc2" else "fxc", fxc, vs_source, vs_profile, "main", False)
            if not aux:
                item["notes"][build] = "no vertex shader could be made for its inputs"
                continue
            with open(aux, "rb") as f:
                if not signatures_agree(inputs, signature(f.read(), True)):
                    item["notes"][build] = "its inputs are laid out in a way the generated vertex shader does not match"
                    continue
        item["builds"].append((build, blob_path, aux))
    return item


def run_harness(items, results_path):
    manifest = os.path.join(WORK, "manifest.txt")
    runnable = [it for it in items if len(it["builds"]) >= 2]
    with open(manifest, "w") as f:
        for it in runnable:
            fields = [it["source"], it["stage"]]
            for build, blob, aux in it["builds"]:
                fields += [build, blob, aux]
            f.write("\t".join(fields) + "\n")
    if os.path.exists(results_path):
        os.remove(results_path)
    start = 0
    while start < len(runnable):
        p = subprocess.run([EXE, manifest, results_path, str(start)], capture_output=True, text=True, errors="replace")
        if p.returncode == 0:
            break
        # the item that was running took the device (or the process) down: note it and go on
        begun, ended = -1, -1
        if os.path.exists(results_path):
            for line in open(results_path, errors="replace"):
                if line.startswith("I "):
                    begun = int(line.split()[1])
                elif line.startswith("E "):
                    ended = int(line.split()[1])
        failed = begun if begun > ended else max(start, ended + 1)
        if failed < len(runnable):
            runnable[failed]["notes"]["harness"] = "stopped the harness (%s)" % (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[-1]
        start = failed + 1
    by_index = {i: it for i, it in enumerate(runnable)}
    if os.path.exists(results_path):
        for line in open(results_path, errors="replace"):
            parts = line.rstrip("\n").split(" ", 5 if line.startswith("D") else 4)
            if len(parts) < 3 or parts[0] not in "RD":
                continue
            it = by_index.get(int(parts[1]))
            if it is None:
                continue
            if parts[0] == "R":
                if parts[3] == "ok":
                    it.setdefault("ns", {})[parts[2]] = float(parts[4].split()[0])
                else:
                    it["notes"][parts[2]] = parts[4] if len(parts) > 4 else "failed"
            else:
                it.setdefault("diff", {})[frozenset((parts[2], parts[3]))] = (float(parts[4]), float(parts[5]))


# ---- report ------------------------------------------------------------------------------

def geomean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values))


def summarise(label, pairs):
    """pairs: [(fxc2 ns, other ns)]"""
    if not pairs:
        return
    ratios = [a / b for a, b in pairs]
    faster = sum(1 for r in ratios if r < 0.97)
    slower = sum(1 for r in ratios if r > 1.03)
    print("  %-30s %4d shaders  time ratio: geometric mean %.3f, median %.3f; "
          "the first faster in %d, within 3%% in %d, slower in %d" % (
              label, len(ratios), geomean(ratios), statistics.median(ratios), faster, len(ratios) - faster - slower, slower))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directories", nargs="+")
    ap.add_argument("--csv")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--limit", type=int, default=0, help="only the first N sources of each directory")
    ap.add_argument("--outliers", type=int, default=8)
    args = ap.parse_args()

    fxc = find_fxc()
    if not fxc:
        sys.exit("fxc.exe (Windows SDK) is needed as the reference")
    if not os.path.exists(EXE):
        sys.exit("build the harness first: tools\\shaderbench\\build.bat")
    os.makedirs(CACHE, exist_ok=True)

    floor_dir = os.path.join(WORK, "(floor)")
    os.makedirs(floor_dir, exist_ok=True)
    for name, text in (("0_0_ps_5_0.hlsl", "float4 main(float4 p : SV_Position) : SV_Target { return 0.5; }\n"),
                       ("0_0_vs_5_0.hlsl", "float4 main(float3 p : POSITION) : SV_Position { return float4(p, 1); }\n")):
        with open(os.path.join(floor_dir, name), "w") as f:
            f.write("// entry: main\n// flags: 0x0\n" + text)
    sources = sorted(glob.glob(os.path.join(floor_dir, "*.hlsl")))
    for d in args.directories:
        found = sorted(glob.glob(os.path.join(d, "*.hlsl")))
        sources += found[:args.limit] if args.limit else found
    print("%d sources; compiling with FXC and fxc2 (cached in %s)..." % (len(sources), os.path.relpath(CACHE, ROOT)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        items = list(pool.map(prepare, [(s, fxc) for s in sources]))

    print("running %d shaders on the GPU..." % sum(1 for it in items if len(it["builds"]) >= 2))
    run_harness(items, os.path.join(WORK, "results.txt"))

    print()
    not_run = {}
    for it in items:
        if it["stage"] not in ("ps", "vs"):
            not_run["%s shaders are not run (only pixel and vertex shaders)" % it["stage"]] = \
                not_run.get("%s shaders are not run (only pixel and vertex shaders)" % it["stage"], 0) + 1
        for build, note in it["notes"].items():
            key = "%s: %s" % (build, re.sub(r"\(.*\)", "", note).strip())
            not_run[key] = not_run.get(key, 0) + 1
    floor = {}
    for it in items:
        if it["dir"] == "(floor)" and "ns" in it:
            floor[it["stage"]] = min(it["ns"].values())
            print("floor, %s: %.4f ns per %s" % (it["stage"], floor[it["stage"]], "pixel" if it["stage"] == "ps" else "vertex"))
    items = [it for it in items if it["dir"] != "(floor)"]
    for it in items:
        it["heavy"] = "ns" in it and min(it["ns"].values()) >= 3 * floor.get(it["stage"], 0)
    for d in args.directories:
        name = os.path.basename(os.path.normpath(d))
        print(name)
        for stage in ("ps", "vs"):
            for what, chosen in (("all", lambda it: True), (">= 3x floor", lambda it: it["heavy"])):
                mine = [it for it in items if it["dir"] == name and it["stage"] == stage and chosen(it)]
                ns = [it["ns"] for it in mine if "ns" in it]
                label = "%s %s," % (stage, what)
                summarise(label + " fxc2 / fxc", [(n["fxc2"], n["fxc"]) for n in ns if "fxc2" in n and "fxc" in n])
                summarise(label + " fxc2 / fxc-od", [(n["fxc2"], n["fxc-od"]) for n in ns if "fxc2" in n and "fxc-od" in n])
                summarise(label + " fxc / fxc-od", [(n["fxc"], n["fxc-od"]) for n in ns if "fxc" in n and "fxc-od" in n])
    measured = [it for it in items if it["heavy"] and "fxc" in it["ns"] and "fxc2" in it["ns"]]
    if measured:
        print("\nwhere fxc2's build is slowest and fastest against FXC's (ns per pixel or vertex; shaders >= 3x floor):")
        ranked = sorted(measured, key=lambda it: it["ns"]["fxc2"] / it["ns"]["fxc"])
        shown = ranked[-args.outliers:][::-1] + [None] + ranked[:args.outliers]
        for it in shown:
            if it is None:
                print("  ...")
                continue
            print("  %-28s %-12s fxc2 %9.3f  fxc %9.3f  ratio %.2f" % (
                it["source"], it["dir"][:12], it["ns"]["fxc2"], it["ns"]["fxc"], it["ns"]["fxc2"] / it["ns"]["fxc"]))
    key, key_od = frozenset(("fxc", "fxc2")), frozenset(("fxc-od", "fxc2"))
    compared = [it for it in items if key in it.get("diff", {})]
    if compared:
        differing = [it for it in compared if it["diff"][key][1] > 0]
        print("\npixel shader output, fxc2 against fxc: %d compared, %d the same (to 0.1%%), %d differ" % (
            len(compared), len(compared) - len(differing), len(differing)))
        for it in sorted(differing, key=lambda it: -it["diff"][key][1])[:args.outliers]:
            note = ""
            if key_od in it["diff"]:
                note = "; fxc2 and FXC without its optimiser agree" if it["diff"][key_od][1] == 0 else \
                    "; differs from FXC without its optimiser too (%.1f%%)" % (100 * it["diff"][key_od][1])
            print("  %-28s %-12s %5.1f%% of pixels, largest difference %.4g%s" % (
                it["source"], it["dir"][:12], 100 * it["diff"][key][1], it["diff"][key][0], note))
    if not_run:
        print("\nnot measured:")
        for key, count in sorted(not_run.items(), key=lambda kv: -kv[1]):
            print("  %4d  %s" % (count, key))

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["directory", "source", "profile", "fxc_ns", "fxc2_ns", "fxc_od_ns", "fxc2_over_fxc", "at_least_3x_floor",
                        "output_max_difference", "output_fraction_differing", "notes"])
            for it in items:
                ns = it.get("ns", {})
                diff = it.get("diff", {}).get(frozenset(("fxc", "fxc2")), ("", ""))
                ratio = ns["fxc2"] / ns["fxc"] if "fxc2" in ns and "fxc" in ns else ""
                w.writerow([it["dir"], it["source"], it["profile"], ns.get("fxc", ""), ns.get("fxc2", ""), ns.get("fxc-od", ""),
                            ratio, int(it.get("heavy", False)), diff[0], diff[1], "; ".join("%s: %s" % kv for kv in it["notes"].items())])
    return 0


if __name__ == "__main__":
    sys.exit(main())
