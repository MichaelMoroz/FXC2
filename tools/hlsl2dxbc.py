#!/usr/bin/env python3
"""HLSL -> DXBC without fxc, through a choice of front ends.

Every route ends in bin/fxc2.exe (vkd3d-shader), the only open DXBC code
generator; the routes differ in what parses the *source* language:

  direct  HLSL --fxc2--> DXBC
          Fastest, no extra tools. Limited to the HLSL that vkd3d-shader
          implements (classic FXC-era HLSL, no templates / HLSL 2021).

  slang   HLSL/Slang --slangc--> plain HLSL --fxc2--> DXBC
          Slang parses the source (generics, interfaces, modules, most of
          HLSL 2021) and lowers it to simple HLSL that vkd3d handles.

  dxc     HLSL --dxc -spirv--> SPIR-V --spirv-cross--> plain HLSL --fxc2--> DXBC
          DXC parses the source (full modern HLSL, templates, HLSL 2021).
          SPIR-V in the middle also allows spirv-opt, or any other SPIR-V
          producer (GLSL via glslang, WGSL via naga/tint, ...).

  auto    try direct, then slang, then dxc; first one that compiles wins.

slangc, dxc and spirv-cross are looked up in PATH and the Vulkan SDK.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FXC2 = os.path.join(ROOT, "bin", "fxc2.exe")

STAGES = {"vs": "vert", "ps": "frag", "gs": "geom", "hs": "tesc", "ds": "tese", "cs": "comp"}


class StepFailed(Exception):
    pass


def tool(name):
    path = shutil.which(name)
    if not path and os.environ.get("VULKAN_SDK"):
        path = shutil.which(name, path=os.path.join(os.environ["VULKAN_SDK"], "Bin"))
    if not path:
        raise StepFailed("%s not found in PATH or the Vulkan SDK" % name)
    return path


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise StepFailed("%s failed:\n%s" % (os.path.basename(cmd[0]), (p.stdout + p.stderr).strip()))
    return p.stdout + p.stderr


def fxc2(src, args, entry, extra=()):
    cmd = [FXC2, "-T", args.profile, "-E", entry, src, *extra]
    for flag, value in (("-Fo", args.Fo), ("-Fh", args.Fh), ("-Fc", args.Fc), ("-Vn", args.Vn)):
        if value:
            cmd += [flag, value]
    if args.unroll is not None:
        cmd += ["-unroll", str(args.unroll)]
    return run(cmd)


def defines(args, fmt):
    return [fmt % d for d in args.D]


def via_direct(args, tmp):
    extra = []
    for d in args.D:
        extra += ["-D", d]
    for i in args.I:
        extra += ["-I", i]
    return fxc2(args.source, args, args.entry, extra)


def via_slang(args, tmp):
    lowered = os.path.join(tmp, "lowered.hlsl")
    cmd = [tool("slangc"), args.source, "-profile", args.profile, "-entry", args.entry, "-target", "hlsl",
           "-line-directive-mode", "none", "-o", lowered]
    cmd += defines(args, "-D%s")
    for i in args.I:
        cmd += ["-I", i]
    run(cmd)
    if args.keep:
        shutil.copy(lowered, args.keep)
    # slang keeps the entry point name in its HLSL output.
    return fxc2(lowered, args, args.entry)


def via_dxc(args, tmp):
    spv = os.path.join(tmp, "shader.spv")
    lowered = os.path.join(tmp, "lowered.hlsl")
    stage = args.profile[:2]
    # DXC only knows SM6 profiles; the SPIR-V does not depend on which one.
    cmd = [tool("dxc"), "-spirv", "-T", stage + "_6_0", "-E", args.entry, "-fspv-target-env=vulkan1.1",
           "-fvk-use-dx-layout", "-Fo", spv, args.source]
    cmd += defines(args, "-D%s")
    for i in args.I:
        cmd += ["-I", i]
    run(cmd)
    major, minor = args.profile[3], args.profile[5]
    run([tool("spirv-cross"), spv, "--hlsl", "--shader-model", major + minor, "--stage", STAGES[stage],
         "--entry", args.entry, "--output", lowered])
    if args.keep:
        shutil.copy(lowered, args.keep)
    # spirv-cross always names the HLSL entry point "main".
    return fxc2(lowered, args, "main")


ROUTES = {"direct": via_direct, "slang": via_slang, "dxc": via_dxc}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("-T", dest="profile", required=True, help="target profile, e.g. ps_5_0")
    ap.add_argument("-E", dest="entry", default="main")
    ap.add_argument("-Fo", help="output DXBC object")
    ap.add_argument("-Fh", help="output C header")
    ap.add_argument("-Fc", help="output assembly listing")
    ap.add_argument("-Vn", help="variable name for -Fh")
    ap.add_argument("-D", action="append", default=[], metavar="NAME[=VALUE]")
    ap.add_argument("-I", action="append", default=[], metavar="DIR")
    ap.add_argument("--via", choices=list(ROUTES) + ["auto"], default="auto")
    ap.add_argument("--unroll", type=int, help="implicit loop unroll limit passed to fxc2")
    ap.add_argument("--keep", metavar="FILE", help="save the intermediate lowered HLSL here")
    args = ap.parse_args()

    routes = list(ROUTES) if args.via == "auto" else [args.via]
    errors = []
    with tempfile.TemporaryDirectory(prefix="hlsl2dxbc") as tmp:
        for route in routes:
            try:
                out = ROUTES[route](args, tmp)
            except StepFailed as e:
                errors.append("[%s] %s" % (route, e))
                continue
            if out.strip():
                print(out.strip())
            if args.via == "auto" and route != "direct":
                print("hlsl2dxbc: compiled via '%s'" % route, file=sys.stderr)
            return 0
    print("\n".join(errors), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
