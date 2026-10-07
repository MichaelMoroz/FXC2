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
| `patches/` | 45 patches on top of upstream vkd3d (see below); `tools/vkd3d-patch-scripts/` has the scripts they were made with. |
| `tools/replay.py` | Recompiles sources the DLL captured (a Unity project's, say) with and without the optimisations and with FXC, and compares. |
| `shaderemu/rvc_opt-fxc2.patch` | The changes to ShaderEmu's shader described under "The emulator shader" (merged there since). |
| `tools/unity_render_shaders.cs`, `tools/compare_images.py` | Render every shader in a Unity folder with fxc2 and with the stock compiler, and compare the pictures. |
| `scripts/unity-overlay.ps1` | Makes a junction-based copy of a Unity editor that compiles with fxc2, leaving the real install untouched. |
| `tools/failsrc.py` | Shows the source lines behind errors in sources the DLL saved (call tracing, below). |
| `tools/se_matrix.py` | Benchmarks ShaderEmu under FXC, DXC or fxc2 with any setting of the tuning switches. |
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
(`scripts/unity-overlay.ps1`) with a shader cache built only by fxc2. These are
with patches 1 to 42 (the Poiyomi run below is with all 45):

- All 153 passes of the project's shaders compile: 342 `D3DCompile` calls,
  0 failures.
- The project's EditMode suite, which compares real shader output with an
  independent CPU reference: 443 of 444 pass, including all 276 `VRCFluidTests`.
  The stock compiler gives the same 443 of 444; the one failure
  (`GraphNodeTests.CheckHelpURLsForSystemNodes`) is a VRChat SDK test that fails
  either way. This suite is what caught the one wrong optimisation of this
  round (see patch 41): five collider tests failed until it was removed, while
  every test in `tests/` passed.
- GPU time per frame in play mode (the fluid running; `FrameTimingManager`,
  30 one-second averages from game time 30 s on, one run each, same session):

  | shaders compiled by | GPU ms per frame, median (min to max) |
  |---|---|
  | FXC (stock editor) | 0.724 (0.668 to 0.789) |
  | fxc2, optimisations off | 0.691 (0.615 to 0.813) |
  | fxc2 | 0.633 (0.565 to 0.706) |

  The ranges overlap and each is a single run, so read this as "not slower
  than FXC, and the optimisations help", not as a 12% win.
- An edit-mode render of the scene (taken with an earlier build) differs from
  the stock-compiler render by at most 3/255 per channel.

**The same project's shaders, offline.** With `%TEMP%\fxc2.dump.on` present the
DLL saves every source it is given; `tools/replay.py` compiles those 342 again
with fxc2, with fxc2's optimisations switched off, and with FXC, checks that
D3D11 accepts each one and counts instructions:

| | shaders | instructions | vs FXC, total | vs FXC, median |
|---|---|---|---|---|
| FXC | 342 | 56,582 | | |
| fxc2, optimisations off | 342 | 121,428 | 2.15x | 2.08x |
| fxc2 | 342 | 75,039 | 1.33x | 1.17x |

The optimisations make 278 of the 342 smaller, leave 63 as they were and make
one larger (a shader that picks one of several textures in a `switch`, which is
lowered to an if chain; that lowering is worth 2 to 3% on ShaderEmu). Against
FXC, 6 are smaller, 103 the same size and 233 larger. Instruction counts are
not speed (see the next section), but they are what can be compared for 342
shaders at once, and all of them load.

**Poiyomi Toon 10.0.24** (the seven built-in-pipeline shaders, 3.3 to 7 MB of source each),
dropped into the same Unity project, in an editor that compiles with fxc2 and in the stock one.

- As shipped (default material): all 44 passes compile, 0 failures.
- With every keyword of each shader enabled and every `*Enable*` property set to 1 (a
  combination no avatar uses, chosen to reach as much of the source as possible): all variants
  compile, 0 failures of 222 compiles. The first attempt had 42 failures, all of which FXC
  compiles, from three gaps that are now closed (patch 44): struct member functions (the decal
  code), `SampleGrad` on a texture array, and `SV_InstanceID` as a geometry shader input.
- Those 42 variants, recompiled offline: D3D11 accepts all of them; 519,949 instructions
  against FXC's 357,913 (1.45x).
- A lit sphere and cube rendered with each shader in both configurations, fxc2 against FXC:
as shipped (plus a test texture and a tinted, dimmed light, so that the picture is not flat)
  all seven pictures are identical to the last bit. With everything enabled both compilers give
  the same saturated white objects, with silhouettes that differ in about 2% of the pixels;
  rendering twice with the *same* compiler a minute apart differs by more (3%), because that
  configuration switches on time-driven vertex effects. So that picture shows that the shaders
  run, not that they agree.
- Compile time, one all-features pixel shader variant (about 14,000 instructions out) and one
  as-shipped one, outside Unity: fxc2 12.4 s and 3.9 s; FXC 52.6 s and 14.2 s. But Poiyomi's
  shaders carry `#pragma skip_optimizations d3d11` until they are locked, and FXC without its
  optimiser takes 4.9 s and 2.4 s (and emits half as much code again). fxc2 has no such mode:
  it always optimises. So in the editor, on unlocked Poiyomi materials, the stock compiler is
  the faster one, by 2 to 4 times (rendering all fourteen configurations cold took 891 s
  against 233 s); where FXC optimises, fxc2 is about 4 times faster.
- Member functions are compiled as functions that take every field of the struct as an `inout`
  parameter, and Poiyomi's decal struct has about 70, so every call copies 70 values in and
  out before the optimiser removes what it can. How much of the compile time that is was not
  measured.

**ShaderEmu** (a RISC-V machine in a pixel shader; `rvc_harness --d3d11` with
`d3dcompiler_47.dll` placed next to the executable).

| | FXC | fxc2 |
|---|---|---|
| `CPUTick` fragment pass, compile time | 533.1 s | 7.8 s |
| bytecode size of that pass | 348,572 bytes | 530,048 bytes |
| state hash, 600 fixed-timestep frames | `635acdc94aff149f` | `635acdc94aff149f` |
| state hash, 6000 frames | `d3384baf5ab1cd3f` | `d3384baf5ab1cd3f` |
| Linux boot to `/ # `: guest instructions | 42,352,129 | 42,352,129 |
| Linux boot: console output (7,312 bytes) | | identical |
| Linux boot: emulation speed | 1,488k IPS | 1,472k IPS |
| 6000-frame bench: emulation speed | 1,595k IPS | 1,570k IPS |

So the emulated machine behaves identically, the shader compiles about 70
times faster, and the same source runs within 1 to 2% of FXC's build. (That
table is from the first round of code-generation work, patches 14 to 29. With
the shader changes fxc2 makes possible it is well ahead: see "The emulator
shader".) Only the upstream `linux` image was booted then; `linux-net` and the
raytracer were run for the later work.

## Performance of the generated code

The first build that ran ShaderEmu correctly was 15% slower than FXC's
(1,350k against 1,580k IPS). It is now within 2%. What was measured, with
`tools/se_matrix.py` (ShaderEmu's `--bench` mode; repeat runs agree to about
0.3%, where fps counters and GPU timer queries drifted by several percent):

| compiler | IPS | fixed cost per frame | per emulated instruction |
|---|---|---|---|
| DXC, D3D12 | 2,003k | 0.430 ms | 288 ns |
| FXC, D3D11 | 1,595k | 0.693 ms | 287 ns |
| fxc2, D3D11 | 1,570k | 0.685 ms | 300 ns |

Two things follow from splitting the time that way. DXC's lead on this machine
is all fixed per-frame cost, which comes from the D3D12 harness and a source
option (`L1_LOCAL`), not from better code in the emulation loop: per
instruction DXC and FXC are equal. And fxc2 matches FXC's fixed cost and is
about 4% behind per instruction.

What moved the number, and what did not (each switch below turns one thing off
or changes a limit, so this can be repeated on another GPU):

| change | switch | effect on ns per instruction |
|---|---|---|
| struct variables split into per-field variables | `VKD3D_HLSL_SPLIT_STRUCTS=0` | 311 -> 322 without |
| reuse of repeated loads and common subexpressions | `VKD3D_HLSL_VALUE_NUMBERING=0` | 311 -> 321 without |
| code after `if (c) return x;` moved into the else branch | `VKD3D_HLSL_RETURN_ELSE=0` | 311 -> 322 without |
| small tails duplicated instead of testing a "returned" flag | `VKD3D_HLSL_RETURN_DUP=<n>` | 312 at 0, 311 at 24, 298 at 200 (default) |
| ifs with small bodies become selects | `VKD3D_HLSL_FLATTEN=<n>` | 326 at 0, 311 at 10 (default), 305 at 30 |
| values used in loops get a register to themselves | `VKD3D_PACK_REGISTERS=0/1` | per instruction equal; packing everything costs 0.14 ms of fixed time |
| variables read in place instead of copied per load | `VKD3D_HLSL_ELIDE_LOADS=0` | within noise, 10% smaller bytecode |
| `switch` without `[forcecase]` as an if chain, like FXC | `VKD3D_HLSL_SWITCH=1` | within noise |
| returns inside switch cases handled as ifs | `VKD3D_HLSL_RETURN_SWITCH=0` | within noise |
| multiplication and unsigned division by powers of two as shifts | (always on) | about 1% |
| small constant loops unrolled within a budget | `VKD3D_HLSL_UNROLL_BUDGET=<n>` | within noise here |
| branches that store to arrays left as branches | `VKD3D_HLSL_KEEP_ARRAY_BRANCHES=0` | within noise |

The pattern: this driver redoes instruction-level cleanup itself, so removing
thousands of redundant instructions barely registers, while anything that
changes the shape of control flow, or which values share a register, does.
That matches the shader author's own notes (branches and merges after them
dominate the per-pixel cost of this loop).

Later patches, measured the same way. None of them moves ShaderEmu's same-source
number beyond noise (it stays at 98 to 99% of FXC's build); what they change is
the size of ordinary shaders, as counted over the Unity project above:

| change | switch | Unity shaders, instructions vs FXC |
|---|---|---|
| (before) | | 1.62x |
| dead code found from the outputs back, `dot(x, 0)` folded (33) | `VKD3D_HLSL_ADCE=0`, `VKD3D_HLSL_SPLIT_RANGES=0` | 1.49x |
| results computed into their destination, variables and swizzles read in place, `add_sat` and friends (34, 36, 37) | `VKD3D_FORWARD_STORES=0` | 1.35x |
| `if_z`, `breakc`, `continuec` (35) | (same switch) | 1.33x |
| `inout` arrays worked on in place (38) | `VKD3D_HLSL_ALIAS_ARRAYS=0` | no change here; see below |

The first of those is what a keyword-heavy surface shader needs: one of this
project's went from 1,149 instructions to 134 (FXC: 119), because a light loop
whose result is multiplied by a zeroed-out light is now removed.

### The emulator shader

With compiles taking 9 seconds instead of 9 minutes the shader itself can be
tuned on D3D11, and two things in it only fxc2 can compile.
The changes are in ShaderEmu itself now (`docs/fxc2.md` there);
`shaderemu/rvc_opt-fxc2.patch` is the same thing as a patch against the commit
before them. Under FXC the shader builds and behaves as before.

- **`inout` arrays by reference (patch 38).** The shader's `L1_LOCAL` option
  makes its 1024-entry write cache a local array handed down through a dozen
  functions, so that it is not zeroed at the start of every pass. FXC cannot
  compile that at all (`error X3531: can't unroll loops marked with loop
  attribute`), and vkd3d copied the array in and out at every call: a 2 MB
  shader that did not run. Now such an array is the caller's own wherever that
  cannot be told from a copy. The shader patch does the same for the two
  768-entry TLB arrays and switches both on when `__FXC2__` is defined.
- **`mulhi()`, `umulExtended()`, `imulExtended()` (patch 42).** The `umul` and
  `imul` instructions return both halves of a 32 x 32 bit product; HLSL can
  only ask for the low one. `umulExtended(a, b, hi, lo)` is one `umul` with
  both destinations, `mulhi(a, b)` the high half alone (signed for `int`). The
  emulator's MULH was four multiplications and a carry chain.
- `sfence.vma` with an address flushes that page's TLB entries instead of all
  of them (plain HLSL, works under FXC too): 60% fewer page walks over a boot.

| ShaderEmu on D3D11, same machine and session | FXC | fxc2 |
|---|---|---|
| `CPUTick` compile time | 554 s | 9.3 s |
| 6000-frame bench, 2,048 instructions a frame | 1,528k IPS | 1,970k IPS |
| fixed cost per frame | 0.714 ms | 0.382 ms |
| 1500 frames at 16,384 instructions a frame | 2,604k IPS | 2,810k IPS |
| Linux cold boot, 21,000 frames | 30.2 s | 22.6 s |
| state hashes; boot instruction count (41,545,138) and console output | | identical |

The gain is nearly all fixed cost: zeroing the three arrays was 0.4 ms of every
pass. Per emulated instruction the two builds are about equal (the split that
`se_matrix.py` prints, 304 against 321 ns, overstates fxc2's share: at 16,384
instructions a frame the whole difference is the fixed part and a little more).
The raytracer guest (73,669,730 instructions, machine mode, where MULH matters)
ran at 4.18M IPS with `mulhi()` and at 3.96M and 4.13M in two runs without, with
the same final state: a gain of a few percent at most.

The machine these were taken on drifted by up to 8% between sessions (FXC's
bench figure was 1,595k on one day and 1,493k to 1,536k on another), so only
numbers from one session are compared with each other.

One difference from FXC found on the way: for a `switch` whose only label is
`default`, FXC drops the body entirely (the test returned 0 where the source
adds 0.0625); vkd3d executes it. That is left as it is.

## Results

Measured on this machine by `tests/run.py`, `tests/bench.py` and
`tests/features.py`; FXC 10.0.26100 is the reference.

**Correctness.** All 24 test shaders compile (22 directly, one each through
the Slang and DXC routes). The 23 that target SM4+ are accepted by the D3D11
runtime, on WARP and on the hardware GPU (`--gpu`); the SM3 one is only checked
to compile, nothing loads it into D3D9. The 17 pixel shaders with
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
[docs/features.md](docs/features.md)): direct 71, via Slang 64, via DXC 63, at
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

Direct-only gaps that a front end fixes: namespaces,
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

Patches 14 to 29 are about the speed of the generated code (see "Performance
of the generated code"): scalar replacement of struct variables (14), shifts
for powers of two (15), value numbering (16), reading variables in place (17),
loop-aware register packing (18, 28), the tuning switches (19, 21), switches
as if chains (20, 26, 29), restructuring of early returns (22, 24), no
flattening of branches that touch arrays (23), an optional round-robin
register allocator (25) and budgeted loop unrolling, which replaces patch 1's
blanket "never unroll" and fixes implicit limits silently truncating loops
(27).

Patches 30 to 42:

30. `mul(matrix, vector)` with one instruction per register instead of two per
    element (`VKD3D_HLSL_SCALAR_MUL` restores the old code).
31. `a * b + c` as `mad` unless IEEE strictness is asked for
    (`VKD3D_HLSL_MAD=0`).
32. `float4(1, 1, 1, x)` stores its constants as one vector; `mov r1, r1`
    left by register allocation is dropped.
33. **Dead code from the outputs back.** What is needed is what has an effect
    (outputs, resource writes, discards) and whatever that uses, including the
    control flow around it; the rest goes, whole loops included. A variable
    assigned as a whole at the top level of the function counts as a new
    variable from there on, so "fill in a structure, reset it, fill it in
    again" does not keep the first lot. Also `dot(x, 0)` is 0.
34. **Results go where they are going.** `dp3 r5.x, ...` / `mov r4.y, r5.x`
    becomes `dp3 r4.y, ...`, and `mov_sat` after an instruction becomes that
    instruction's `_sat`. Two thirds of the surplus `mov`s were of this kind.
35. `not` + `if_nz` is `if_z`; `if` / `break` / `endif` is `breakc`.
36. (and 37) The same for swizzles of values, for values that are stored and
    used, and for copies of variables as far as the variable is unchanged.
38. **`inout` arrays by reference**, and a fix for upstream's propagation of
    `a[i]` to `b[c * i + d]`, which read `b` where `a` was loaded without
    checking that `b` was still the same, and never terminated on two arrays
    assigned to each other (every `inout` array argument).
39. `__FXC2__` is predefined.
40. Per-variable state of two passes is reset from the code, not from the
    scope lists.
41. **A fix for 33.** After removing dead code it put component stores together
    early so that newly small branches would flatten well, with a pass that is
    only correct where it normally runs. That moved stores across loads. No
    test here saw it; five collider tests of the Unity project did.
42. `mulhi()`, `umulExtended()`, `imulExtended()`.
43. The `[fastopt]` and `[allow_uav_condition]` loop attributes are accepted (they only steer
    FXC's optimiser).
44. **Struct member functions.** `struct S { float2 scale; void Init(float2 s) { scale = s; } };`
    and `obj.Init(x)`: the function is compiled as an ordinary one that takes the fields
    declared before it as `inout` parameters ahead of its own, so a field is simply a parameter
    inside it and the call copies back what it changed. Overloads, members calling earlier
    members and parameters that hide a field work; a field declared after the function is not
    visible in it, and there is no `this`. Also `SampleGrad` on array textures (the gradients do
    not include the array index) and `SV_InstanceID`/`SV_VertexID` as geometry and hull shader
    inputs.
45. Compile time on very large shaders: the search for expressions to put in one vector
    instruction compared each with every group found so far, and one flattening check read the
    environment for every load and store. Together a third of the time on a Poiyomi variant.

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
