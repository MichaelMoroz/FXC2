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
| `patches/` | Three small patches on top of upstream vkd3d (see below). |
| `scripts/build-vkd3d.sh` | Reproducible cross-build of everything in `bin/` from WSL/Linux. |

```bash
bin/fxc2.exe -T ps_5_0 -E main -Fo shader.dxbc shader.hlsl
```

```bash
python tools/hlsl2dxbc.py shader.hlsl -T ps_5_0 -Fo shader.dxbc
```

Use `-T` rather than `/T` from Git Bash (MSYS rewrites `/T` into a path).

## Results

Measured on this machine by `tests/run.py`, `tests/bench.py` and
`tests/features.py`; FXC 10.0.26100 is the reference.

**Correctness.** All 12 test shaders compile (10 directly, one each through
the Slang and DXC routes). The 11 that target SM4+ are accepted by the D3D11
runtime, on WARP and on the hardware GPU (`--gpu`); the SM3 one is only checked
to compile, nothing loads it into D3D9. The four pixel shaders with
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
[docs/features.md](docs/features.md)): direct 68, via Slang 62, via DXC 62, at
least one route 73.

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

`double`; `EvaluateAttribute*` / `GetRenderTargetSample*`;
`CalculateLevelOfDetail`; `GetDimensions` on structured buffers;
`IncrementCounter`/`DecrementCounter`; `Append`/`ConsumeStructuredBuffer`;
`RWByteAddressBuffer.Interlocked*` (the free-function form on `RWBuffer`,
`RWTexture` and `RWStructuredBuffer` elements works); `[instance(n)]` geometry
shaders; `SV_Coverage`.

Direct-only gaps that a front end fixes: struct member functions, namespaces,
interfaces/classes, templates, operator overloading.

## Patches carried on vkd3d

Upstream is pinned at `vkd3d-2.1-93-gcfcb4833`.

1. **No speculative loop unrolling for SM4+.** Upstream tries to unroll every
   loop up to 254 iterations to mimic FXC. On the raymarch test that meant
   3 min 56 s and a 3.6 MB shader, against 0.03 s and 12 KB with the loops
   kept. Loops marked `[unroll]` are still unrolled. Because a few shaders are
   only valid when unrolled (a loop counter selecting a texture from an array,
   or used as a texel offset), `fxc2.exe` and the DLL retry a failed compile
   with unrolling enabled. `-unroll <n>` or `VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT`
   forces a limit.
2. **`isnan`, `isfinite`, `reversebits`** intrinsics.
3. **UAV read methods**: `Load`/`Load2-4` on `RWByteAddressBuffer`, `Load` and
   `GetDimensions` on RW textures/buffers, `Load` on structured buffers. This
   includes a fix for raw UAV loads being emitted as `ld_uav_typed`.

None of these have been sent upstream.

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
