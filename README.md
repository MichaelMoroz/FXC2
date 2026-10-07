# FXC2 — HLSL to DXBC without FXC

A working way to compile HLSL to DXBC (D3D10/11 shader bytecode, plus D3D9
bytecode for SM1–3) that never touches Microsoft's `fxc.exe` /
`d3dcompiler_47.dll`, and the investigation behind it.

## Short answer

There is exactly one open-source DXBC *code generator*: **vkd3d-shader**, the
HLSL compiler Wine uses to implement `d3dcompiler`. Every other shader compiler
(DXC, Slang, glslang, naga, Tint) stops at DXIL, SPIR-V or HLSL *text*, and no
DXIL→DXBC or SPIR-V→DXBC translator exists. So every viable route ends in
vkd3d-shader; the only real choice is what parses the source in front of it.

This repo packages that as:

| File | What it is |
|---|---|
| `bin/fxc2.exe` | `fxc.exe`-compatible command line (`/T /E /Fo /Fh /Fc /D /I /Vn ...`). Static, 2 MB, no dependencies. |
| `bin/d3dcompiler_47.dll` | Drop-in replacement for Microsoft's DLL (`D3DCompile`, `D3DCompile2`, `D3DCompileFromFile`, `D3DPreprocess`, `D3DReflect`, `D3DDisassemble`, `D3DStripShader`, ...). Anything that loads `d3dcompiler_47.dll` compiles through vkd3d instead. |
| `bin/vkd3d-compiler.exe` | Upstream vkd3d CLI (also does DXBC → SPIR-V/GLSL/MSL/asm). |
| `tools/hlsl2dxbc.py` | Front-end chooser: `direct`, via Slang, via DXC + SPIRV-Cross, or `auto`. |
| `bin/unity/` | The pair of DLLs Unity needs: a loader-proof stub named `D3DCompiler_47.dll` plus the real compiler as `fxc2_d3dcompiler.dll` (see Unity below). |
| `patches/` | 13 patches on top of upstream vkd3d (see below). |
| `scripts/unity-overlay.ps1` | Makes a junction-based copy of a Unity editor that compiles with fxc2, leaving the real install untouched. |
| `tools/failsrc.py` | Shows the source lines behind errors in sources the DLL saved (call tracing, below). |
| `scripts/build-vkd3d.sh` | Reproducible cross-build of everything in `bin/` from WSL/Linux. |

```bash
bin/fxc2.exe -T ps_5_0 -E main -Fo shader.dxbc shader.hlsl
```

```bash
python tools/hlsl2dxbc.py shader.hlsl -T ps_5_0 -Fo shader.dxbc
```

Use `-T` rather than `/T` from Git Bash (MSYS rewrites `/T` into a path).

## Tested on real projects

**Unity 2022.3 (D3D11), VRCFluid project.** Run through an overlay editor
(`scripts/unity-overlay.ps1`) with a shader cache built only by fxc2.

- All 154 passes of the project's 73 shaders compile: 425 `D3DCompile` calls,
  0 failures.
- The project's EditMode suite, which compares real shader output with an
  independent CPU reference: 443 of 444 pass, including all 276 `VRCFluidTests`.
  The stock compiler gives the same 443 of 444; the one failure
  (`GraphNodeTests.CheckHelpURLsForSystemNodes`) is a VRChat SDK test that fails
  either way.
- An edit-mode render of the scene differs from the stock-compiler render by at
  most 3/255 per channel. In play mode the fluid simulates and renders (water
  in the hot tub and on the slide, about 88 fps); that was judged by eye only,
  no stock play-mode capture was taken to compare against.

**ShaderEmu** (a RISC-V machine in a pixel shader; `rvc_harness --d3d11` with
`d3dcompiler_47.dll` placed next to the executable).

| | FXC | fxc2 |
|---|---|---|
| `CPUTick` fragment pass, compile time | 533.1 s | 6.3 s |
| bytecode size of that pass | 348,572 bytes | 520,608 bytes |
| state hash after 600 fixed-timestep frames | `635acdc94aff149f` | `635acdc94aff149f` |
| Linux boot to `/ # `: guest instructions | 42,352,129 | 42,352,129 |
| Linux boot: console output (7,312 bytes) | | identical |
| Linux boot: emulation speed | 1,428k IPS | 1,201k IPS |
| 600-frame bench: emulation speed | 1,398k IPS | 1,324k IPS |

So the emulated machine behaves identically, the shader compiles about 85
times faster, and it runs 5 to 16% slower. Only the upstream `linux` image was
booted; the project's own `linux-net` image and the GPU-device test images
were not run.

## Results

Measured on this machine by `tests/run.py`, `tests/bench.py` and
`tests/features.py`; FXC 10.0.26100 is the reference.

**Correctness.** All 17 test shaders compile (15 directly, one each through
the Slang and DXC routes). The 16 that target SM4+ are accepted by the D3D11
runtime, on WARP and on the hardware GPU (`--gpu`); the SM3 one is only checked
to compile, nothing loads it into D3D9. The nine pixel shaders with
a render check produce the same image as the FXC build (max channel difference
1.2e-4 on the GPU, float rounding), and the compute shader leaves bit-identical
buffer contents.

**Compile time** (best of 3):

| shader | fxc2 | fxc | speedup | fxc2 insns | fxc insns |
|---|---|---|---|---|---|
| raymarch_ps | 0.03s | 0.09s | 2.9x | 509 | 289 |
| matrix_ps | 0.03s | 0.05s | 1.7x | 230 | 144 |
| blur 31x31 (nested constant loops) | 0.01s | 0.03s | 2.2x | 54 | 29 |
| call chain x8 (generated) | 0.04s | 0.58s | 15.5x | 1709 | 900 |
| call chain x12 (generated) | 0.76s | 118.01s | 154.6x | 12013 | 6386 |

**Generated code.** vkd3d's optimiser is much weaker than FXC's: 1.5–4x as many
DXBC instructions (redundant `mov`s, scalarised matrix math). In the benchmark
that did not show up at run time, because the driver recompiles DXBC anyway:

| shader, 2048x2048 fullscreen draw on the GPU | fxc2 code | fxc code | ratio |
|---|---|---|---|
| raymarch_ps | 7.1 ms | 7.3 ms | 0.98x |
| blur 31x31 | 27.6 ms | 28.1 ms | 0.98x |
| call chain x8 | 11.2 ms | 10.4 ms | 1.08x |
| call chain x12 | 192.4 ms | 185.6 ms | 1.04x |

The draw went to the system's default adapter (this laptop has both an Intel
UHD and an RTX 5070; the harness does not pick between them), and the cheap
shaders are dominated by fixed per-draw overhead, so read this as "no large
regression seen", not as a precise measurement.

**HLSL coverage** (82 feature probes, full table in
[docs/features.md](docs/features.md)): direct 70, via Slang 64, via DXC 63, at
least one route 75.

## The routes

| Route | Pipeline | Extra tools | Use it for |
|---|---|---|---|
| `direct` | HLSL → fxc2 → DXBC | none | Classic FXC-era HLSL. ~20 ms per shader. SM1–SM5.1, all stages, effects. |
| `slang` | HLSL/Slang → `slangc -target hlsl` → fxc2 | slangc | Struct methods, namespaces, Slang generics/interfaces/modules. +0.4 s. |
| `dxc` | HLSL → `dxc -spirv` → `spirv-cross --hlsl` → fxc2 | dxc, spirv-cross | HLSL 2021: templates, operator overloading, `enum class`. +0.2 s. Any other SPIR-V producer (GLSL, WGSL) can enter here too. |
| drop-in DLL | whatever already calls `D3DCompile` | none | Existing tools/engines. e.g. `slangc -target dxbc -fxc-path bin` works unchanged. |

`hlsl2dxbc.py --via auto` tries them in that order.

What the front ends buy is *language* coverage. They lower source to simple
HLSL, so anything the vkd3d back end cannot express fails on every route.

### Things no route compiles today

`EvaluateAttribute*` / `GetRenderTargetSample*`;
`CalculateLevelOfDetail`; `GetDimensions` on structured buffers;
`IncrementCounter`/`DecrementCounter`; `Append`/`ConsumeStructuredBuffer`;
`RWByteAddressBuffer.Interlocked*` (the free-function form on `RWBuffer`,
`RWTexture` and `RWStructuredBuffer` elements works); `SV_Coverage` as a pixel
shader input. Doubles are scalar only, with `+ - * /`, negation and
conversions; double vectors and comparisons are reported as unimplemented.

Direct-only gaps that a front end fixes: struct member functions, namespaces,
interfaces/classes, templates, operator overloading.

## Patches carried on vkd3d

Upstream is pinned at `vkd3d-2.1-93-gcfcb4833`. None of these have been sent
upstream. Each one was needed by a test shader, Unity or ShaderEmu, and each
behaviour change was checked against FXC by executing both builds.

1. **No speculative loop unrolling for SM4+.** Upstream tries to unroll every
   loop up to 254 iterations to mimic FXC: 3 min 56 s and a 3.6 MB shader on
   the raymarch test, against 0.03 s and 12 KB with the loops kept. Loops
   marked `[unroll]` are still unrolled. Shaders that are only valid once
   unrolled (a loop counter selecting a texture, or used as a texel offset)
   are retried with unrolling by `fxc2.exe` and the DLL. `-unroll <n>` or
   `VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT` forces a limit.
2. `isnan`, `isfinite`, `reversebits`.
3. UAV read methods (`Load*` on `RWByteAddressBuffer`, `Load`/`GetDimensions`
   on RW textures and buffers, `Load` on structured buffers), including a fix
   for raw UAV loads being emitted as `ld_uav_typed`.
4. For Unity: `SV_InstanceID`/`SV_VertexID` passed between stages,
   `SV_DepthLessEqual`/`SV_DepthGreaterEqual`, `[instance(n)]` geometry
   shaders, and `GetRenderTargetSampleCount()` in helpers that non-pixel stages
   never call.
5. `float - bool` and `-bool` (negating a bool yields an int).
6. `firstbithigh`/`firstbitlow` under shader model 4, which has no bit-scan
   instructions.
7. **Exponential compile time**: `evaluate_conditionals_recurse()` walked shared
   expression graphs as trees. One Unity variant went from over 3 minutes to
   0.6 s with the recursion bounded.
8. Preprocessor: the result of `##` is looked up as a macro again
   (`#define GET(x) (v >> SHIFT_##x)`).
9. Attributes such as `[branch]` in front of plain statements are accepted and
   ignored; a `switch` case may end in an `if` whose branches both leave it.
10. Stores to a vector component chosen at run time (`v[i] = x` in a real loop).
11. Scalar `double` for shader model 5 (`ftod`, `dadd`, `dmul`, `ddiv`, `dtof`,
    `dtoi`, `dtou`, `itod`, `utod`), with the feature flags D3D11 requires.
    `floor()` and friends on a double are computed in single precision, as FXC
    does.
12. **Parse time**: every `case` label and array size cloned and folded all of
    the shader's static initialisers. ShaderEmu's trivial vertex shader went
    from 21.6 s to 0.2 s.
13. `VKD3D_NO_TRACE_MESSAGES` builds did not compile. The build uses it because
    trace calls evaluate their arguments, string formatting included, even when
    tracing is off.

## Approaches that do not work

- **DXC → DXIL → DXBC.** Nothing converts DXIL (LLVM bitcode) back to DXBC.
  Microsoft's `dxilconv` and themaister's `dxil-spirv` both go the other way.
- **SPIR-V → DXBC directly.** No such back end exists; SPIRV-Cross, naga and
  Tint emit HLSL *text* and expect FXC to finish the job. vkd3d-shader reads
  DXBC/DXIL and writes SPIR-V, not the reverse. Hence the detour through
  SPIRV-Cross text in the `dxc` route.
- **Slang's own `-target dxbc`.** It generates HLSL and calls
  `d3dcompiler_47.dll`. It only becomes FXC-free with the drop-in DLL.
- **Mesa.** Its D3D back end produces DXIL only.

## Unity

Unity's `UnityShaderCompiler.exe` does not `LoadLibrary` its
`Data\Tools\D3DCompiler_47.dll`. It maps the file with a private loader, and a
normal MinGW-built DLL crashes it at start-up. `bin/unity/D3DCompiler_47.dll` is
therefore a 6 KB stub with no C runtime and no imports: it finds the real
`kernel32` through the PEB, loads `fxc2_d3dcompiler.dll` from the same folder
with the regular Windows loader, and forwards every call.

Unity's install folder needs admin rights to modify, so the tested route is an
overlay copy (run it with PowerShell 7, `pwsh`):

```bash
pwsh scripts/unity-overlay.ps1 -Editor "C:\Program Files\Unity\Hub\Editor\2022.3.22f1\Editor" -Dest out\unity-overlay
```

Then start `out\unity-overlay\Unity.exe -projectPath <project>`. Remove it only
with `-Remove`: the folder is full of junctions into the real install, and a
plain recursive delete can follow them.

Unity caches compiled variants in `Library/ShaderCache` regardless of which
compiler produced them, **including failures**, so move that folder aside to
actually exercise fxc2, and restore it to go back.

## Call tracing

Set `FXC2_LOG=<file>`, or create `%TEMP%\fxc2.log.on` for hosts whose
environment is awkward to change, and the DLL logs every compile (profile,
entry point, flags, result, milliseconds). Sources that fail are saved to
`fxc2_fail\` next to the log with the compiler's messages on top, and ones
that take more than two seconds to `fxc2_slow\`. `python tools/failsrc.py
<saved file>` prints the offending source lines, following `#line` directives.
This is how every Unity and ShaderEmu gap above was found.

## Building

`bin/` is checked in. To rebuild, from WSL/Linux:

```bash
bash scripts/build-vkd3d.sh
```

It needs `build-essential mingw-w64 autoconf automake libtool flex bison
pkg-config wine64-tools libwine-dev spirv-headers libvulkan-dev libjson-perl`,
clones vkd3d into `~/fxc2`, applies `patches/`, and writes `bin/`.

## Tests

```bash
python tests/run.py
```

```bash
python tests/run.py --gpu
```

```bash
python tests/features.py
```

```bash
python tests/bench.py --gpu
```

```bash
python tests/test_dll.py
```

`run.py --pipeline slang|dxc` pushes the whole suite through another route.
The tests use `fxc.exe` from the Windows SDK as the reference when present and
skip the comparisons otherwise. The Slang and DXC routes need those tools in
`PATH` or a Vulkan SDK install.

## Licensing

vkd3d is LGPL-2.1-or-later, and `fxc2.exe` / `d3dcompiler_47.dll` link it
statically. Redistributing those binaries means complying with the LGPL
(offer the source and patches, allow relinking); building the DLL as the only
LGPL component and linking it dynamically is the simplest way to stay clean if
this ships inside a closed product.
