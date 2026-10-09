# FXC2 — HLSL to DXBC without FXC

A working way to compile HLSL to DXBC (D3D10/11 shader bytecode, plus D3D9
bytecode for SM1–3) that never touches Microsoft's `fxc.exe` /
`d3dcompiler_47.dll`, and the investigation behind it.

## What this is for

Direct3D 11 runs shaders as DXBC bytecode, and the only compiler that has ever
produced it is Microsoft's FXC (`fxc.exe`, `d3dcompiler_47.dll`): closed, no
longer developed, and slow in a way nobody can fix. Its optimiser takes minutes
on a large shader (nine minutes on the one this started with), and anything it
refuses to compile stays uncompiled. Everything newer (DXC, Slang) produces
DXIL or SPIR-V, which D3D11, and so Unity's built-in pipeline and VRChat, cannot
load.

fxc2 is a second compiler for the same bytecode: vkd3d's HLSL compiler (the
one Wine uses) with 57 patches, packaged as a command line and as a drop-in
`d3dcompiler_47.dll`. What comes out is ordinary DXBC. Whoever runs the result
needs nothing: a Unity build or a VRChat world made with it contains the
bytecode, not the compiler.

## What you gain and what you give up

Numbers are from the sections further down (one laptop, RTX 5070; details and
caveats there).

**Gains**

- **Compile time where FXC is slow.** Shaders FXC's optimiser struggles with
  compile in seconds:

  | shader | FXC | fxc2 |
  |---|---|---|
  | ShaderEmu `CPUTick` (a RISC-V machine in one pixel shader) | 554 s | 9.3 s |
  | upstream rvc's version of the same | 405 s | 5.2 s |
  | Poiyomi Toon, one all-features pixel shader variant | 52.6 s | 12.4 s |
  | generated call chain, 12 deep | 107 s | 3.1 s |
  | small everyday shaders | 0.02 to 0.09 s | 0.01 to 0.03 s |

- **A compiler that can be changed.** It is open source and this repository
  builds it. Things added because a shader needed them: `inout` arrays worked
  on in place (FXC cannot compile ShaderEmu's local-array variant at all;
  with it that shader is 28% faster), `mulhi()` / `umulExtended()` for the
  `umul` instruction HLSL cannot otherwise reach, and `__FXC2__` so one source
  can serve both compilers.
- **Speed of the generated code is about FXC's** on what was measured: equal
  on a Unity project's own shaders, 1% behind on ShaderEmu's tuned shader from
  the same source.
- **It drops in.** Same command line switches as `fxc.exe`, same DLL exports;
  Unity, ShaderEmu's harness and `slangc -target dxbc` use it unchanged.

**Costs**

- **The optimiser is weaker.** More instructions for the same shader (1.33x
  FXC's over a Unity project, 1.45x on Poiyomi's all-features variants). The
  GPU driver hides most of that, but not all: Poiyomi's heavy pixel shaders run
  about 8% slower than FXC's optimised builds (worst case 1.5x), and upstream
  rvc's emulator shader, which nobody shaped for this compiler, runs at 60% of
  its FXC speed.
- **No "skip optimisation" mode.** Unity asks for one for shaders with
  `#pragma skip_optimizations` (unlocked Poiyomi materials); FXC then compiles
  2 to 4 times faster than fxc2, which always optimises. For such shaders in
  the editor the stock compiler is the quicker one.
- **Not all of HLSL.** 71 of 82 feature probes pass (`docs/features.md`).
  Missing: `CalculateLevelOfDetail`, `GetDimensions` on structured buffers,
  buffer counters and `Interlocked*` on raw buffers, namespaces, classes and
  interfaces, templates. Slang or DXC in front (see "The routes") cover the
  language ones.
- **Results are not bit-identical to FXC's.** Different instructions round
  differently; in one of 252 pixel shaders compared that showed as a visible
  difference (coordinates near 65,000 multiplied out and used to sample
  noise). FXC's own optimised and unoptimised builds differ the same way in
  another.
- **It is young and has been wrong.** Two miscompiles were found by real
  projects during this work and are fixed: one of this repository's own
  optimisations (caught by a Unity project's tests) and one in vkd3d (`float -
  uint` negated the unsigned value first; ShaderEmu's terminal showed it).
  There are 27 execution tests here and the projects below; check what you
  ship.
- **Not exercised:** shader model 1 to 3 output is compiled but never run;
  geometry, hull and domain shaders are checked to load and to render in
  Unity, but not timed.

## How to use it

### Unity (built-in pipeline, D3D11)

Unity compiles shaders with the `D3DCompiler_47.dll` in its editor folder, so
the swap is made there. The supported way leaves the installed editor alone
and makes a second, lightweight copy of it (0.5 GB; everything but the tools
folder is a junction to the real install):

1. Close Unity. In PowerShell 7:

   ```bash
   pwsh scripts/unity-overlay.ps1 -Editor "C:\Program Files\Unity\Hub\Editor\2022.3.22f1\Editor" -Dest out\unity-overlay
   ```

2. Move the project's `Library\ShaderCache` folder and `Library\ShaderCache.db`
   somewhere else. Unity caches compiled variants there whichever compiler
   made them, failures included, so with the old cache in place most shaders
   would not be recompiled at all.
3. Start `out\unity-overlay\Unity.exe -projectPath <project>` and work as
   usual. Every shader the editor compiles now goes through fxc2. That was
   tested for the scene view, play mode and the test runner; a player or
   asset-bundle build uses the same compiler process, but none was made.
4. To go back: close it, put the cache folder back, start the normal editor.
   Remove the overlay only with the script's `-Remove` (a plain recursive
   delete can follow the junctions into the real install).

To patch an editor in place instead (needs admin rights; the same two files
as the overlay uses, but this way round was not tried): rename
`<Editor>\Data\Tools\D3DCompiler_47.dll`, then copy both files from
`bin/unity/` there. The pair is needed because Unity's shader compiler maps
that DLL with a loader of its own; the 6 KB `D3DCompiler_47.dll` is a stub
that loads the real compiler, `fxc2_d3dcompiler.dll`, the normal way.

Good to know:

- `#ifdef __FXC2__` tells the compilers apart in shader code.
- Create `%TEMP%\fxc2.log.on` and every compile is logged to
  `%TEMP%\fxc2.log` (profile, entry point, result, milliseconds); sources that
  fail are saved to `%TEMP%\fxc2_fail\` with the messages on top. With
  `%TEMP%\fxc2.dump.on` every source is saved to `fxc2_all\`, which is what
  `tools/replay.py` and `tools/shaderbench.py` take.
- If a shader fails only with fxc2, that saved source plus
  `python tools/failsrc.py <file>` shows the line.
- `#pragma skip_optimizations` has no effect (see Costs).
- Tested with Unity 2022.3.22f1 on two projects (below). Other versions should
  work the same way; they were not tried.

### Command line

```bash
bin/fxc2.exe -T ps_5_0 -E main -Fo shader.dxbc shader.hlsl
```

`/T /E /Fo /Fh /Fc /D /I /Vn /Gec /P` and the rest of the common `fxc.exe`
switches. Use `-T` rather than `/T` from Git Bash (MSYS rewrites `/T` into a
path). `python tools/hlsl2dxbc.py` puts Slang or DXC in front for HLSL 2021
features (see "The routes").

### Any program that calls D3DCompile

Put `bin/d3dcompiler_47.dll` next to the executable. That is how ShaderEmu's
harness uses it (its `docs/fxc2.md`). Programs that share a shader cache
between runs need a separate cache per compiler.

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
| `patches/` | 57 patches on top of upstream vkd3d (see below); `tools/vkd3d-patch-scripts/` has the scripts they were made with. |
| `tools/replay.py` | Recompiles sources the DLL captured (a Unity project's, say) with and without the optimisations and with FXC, and compares. |
| `shaderemu/rvc_opt-fxc2.patch` | The changes to ShaderEmu's shader described under "The emulator shader" (merged there since). |
| `tools/unity_render_shaders.cs`, `tools/compare_images.py` | Render every shader in a Unity folder with fxc2 and with the stock compiler, and compare the pictures. |
| `scripts/unity-overlay.ps1` | Makes a junction-based copy of a Unity editor that compiles with fxc2, leaving the real install untouched. |
| `tools/failsrc.py` | Shows the source lines behind errors in sources the DLL saved (call tracing, below). |
| `tools/shaderbench.py`, `tools/shaderbench/` | Times captured shaders on the GPU, FXC's build against fxc2's, without the application (see "Speed of the generated code, shader by shader"). |
| `tools/se_matrix.py` | Benchmarks ShaderEmu under FXC, DXC or fxc2 with any setting of the tuning switches. |
| `scripts/build-vkd3d.sh` | Reproducible cross-build of everything in `bin/` from WSL/Linux. |

```bash
python tools/hlsl2dxbc.py shader.hlsl -T ps_5_0 -Fo shader.dxbc
```

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
`d3dcompiler_47.dll` placed next to the executable). Three shaders, each run
under both compilers in the same session, 6000 frames at 2,048 emulated
instructions a frame; the state hash after them is the same for both
compilers in every row:

| shader | | FXC | fxc2 |
|---|---|---|---|
| `experiments/rvc_opt`, as each compiler builds it (fxc2: local arrays, `mulhi`) | compile | 554 s | 9.3 s |
| | speed | 1,528k IPS | 1,970k IPS |
| the same with static arrays under fxc2 too (`L1_STATIC`) | speed | | 98 to 99% of FXC's |
| upstream rvc, unmodified | compile | 405 s | 5.2 s |
| | speed | 583k IPS | 351k IPS |

A Linux cold boot on `rvc_opt` ends after the same 41,545,138 instructions
with the same console output under both, in 30.2 s (FXC) and 22.6 s (fxc2).
The project's `linux-net` image, the raytracer guest and the DXC/D3D12 build
were run as well; the GPU-device test images were not.

Upstream's shader is the open case: per emulated instruction fxc2's build
takes 2.5 us against FXC's 1.4, and none of the tuning switches below changes
that. It compiles only since patch 46 (its `4294967296.0l` literal), so no
work has gone into it yet.

## Performance of the generated code

This section is the record of tuning on one shader, ShaderEmu's `rvc_opt`
tick pass, compiled from the same source by both. The first build that ran it
correctly was 15% slower than FXC's (1,350k against 1,580k IPS); after patches
14 to 29 it was within 2%, and it has stayed at 98 to 99% since. What was
measured then, with `tools/se_matrix.py` (ShaderEmu's `--bench` mode; repeat
runs agree to about 0.3%, where fps counters and GPU timer queries drifted by
several percent):

| compiler (at patch 29) | IPS | fixed cost per frame | per emulated instruction |
|---|---|---|---|
| DXC, D3D12 | 2,003k | 0.430 ms | 288 ns |
| FXC, D3D11 | 1,595k | 0.693 ms | 287 ns |
| fxc2, D3D11 | 1,570k | 0.685 ms | 300 ns |

Two things follow from splitting the time that way. DXC's lead on this machine
is all fixed per-frame cost, which comes from the D3D12 harness and a source
option (`L1_LOCAL`), not from better code in the emulation loop: per
instruction DXC and FXC are equal. And fxc2 matched FXC's fixed cost and was
about 4% behind per instruction. (`L1_LOCAL` is what fxc2 can compile since
patch 38; current figures are under "The emulator shader".)

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

#### Against DXC on D3D12

ShaderEmu's other backend, D3D12 with DXC, was 16% faster than D3D11 with fxc2
on the Linux bench. Its DXIL has arbitrary control flow; in D3D11 bytecode a
function that returns `bool` through early returns becomes a flag that is
written, copied and tested. On the emulator's commonest instruction both
compilers emitted about 120 operations, but fxc2's had 6 branches where DXC's
had 4, and a branch costs as much as six additions there. Patches 49 and 50,
and a loop in the shader that leaves by `break` from the place that decides
it, removed that; the harness now also commits only the bands of RAM that were
written on D3D11, as it did on D3D12. D3D11 with fxc2 is level with DXC or
ahead now. Same session, state hashes equal:

| | D3D11 + fxc2 before | D3D11 + fxc2 | D3D12 + DXC |
|---|---|---|---|
| fixed cost of a frame | 0.37 ms | 0.083 ms | 0.091 ms |
| Linux bench, 2,048 instructions a frame | 2,759k IPS | 3,280k IPS | 3,256k IPS |
| the same at 16,384 | 3,187k IPS | 3,660k IPS | 3,651k IPS |
| Linux cold boot, 21,000 frames | 16.1 s | 13.74 s | 14.24 s |
| raytracer guest, 40,000 frames | | 4,198k IPS | 4,046k IPS |
| gears (the machine's GPU device) | | 3,786k IPS | 3,566k IPS |

Two of the four steps were not the compiler's: the commit in bands, and a
`Flush` at the end of the harness's D3D11 frame (the GPU was handed the frame
only when the readback's `Map` asked for it, 7% at 2,048 instructions a frame).

On the tick pass alone the bytecode is ahead of DXC's and the API behind:
ShaderEmu's harness can give fxc2's bytecode to D3D12 (`RVC12_DXBC=1`), and
there the raytracer's tick takes 0.331 ms against 0.348 for DXC's DXIL. The
same bytecode through D3D11 takes 0.355 to 0.365.

The machine these were taken on drifted by up to 8% between sessions (FXC's
bench figure was 1,595k on one day and 1,493k to 1,536k on another), so only
numbers from one session are compared with each other.

### Speed of the generated code, shader by shader

`tools/shaderbench.py` takes the sources the DLL captured from an application,
compiles each with FXC and with fxc2, and times both builds on the GPU in a
small harness of its own (`tools/shaderbench/`, D3D11, C++): no editor, 550
shaders in a few minutes once FXC's builds are cached.

```bash
tools\shaderbench\build.bat
```

```bash
python tools/shaderbench.py out/unity_sources out/poiyomi_sources --csv out/shaderbench.csv
```

Each shader gets whatever it reads made up from its reflection data, the same
for both builds: constant buffers filled by variable name and type (floats
0.25 to 0.75, matrices near identity, integers 1 to 3), small noise textures,
zeroed buffers. Pixel shaders are timed per pixel on a 1024 x 1024 target,
vertex shaders per vertex over 65,536 points a draw, and each pixel shader's
output is compared between the builds. Geometry, hull, domain and compute
shaders are not run.

What that can and cannot tell: it compares two builds of a shader on one path
through it. Which branch a material property selects is down to the made-up
value, so this is not what a frame costs in the application; and a shader that
does little sits at the cost of drawing at all (the "floor": 0.031 ns a pixel,
0.19 ns a vertex), where no compiler can differ.

| shaders (time of fxc2's build / FXC's, geometric mean) | measured | all | those at least 3x the floor |
|---|---|---|---|
| VRCFluid project and Unity's own, pixel | 151 | 0.99 | 1.00 (5 shaders) |
| VRCFluid project and Unity's own, vertex | 139 | 1.00 | |
| Poiyomi Toon variants, pixel | 101 | 1.05 | 1.085 (65 shaders) |
| Poiyomi Toon variants, vertex | 89 | 1.02 | |
| Poiyomi pixel, against FXC with optimisation skipped (what the editor runs for unlocked materials) | 84 | 0.93 | 0.91 (65 shaders) |

So on this project's shaders with these inputs there is nothing between the
compilers, mostly because few of them do enough to measure. On Poiyomi's,
which do, fxc2's code is 8% slower than FXC's optimised code in the mean (41
of 65 slower, 20 faster; from 0.84x to 1.53x) and 9% faster than what FXC
produces when told not to optimise. The slowest family (2.0 against 3.0 ns a
pixel) is where to look next.

It was looked at (patches 54 to 56): that family ran 46 small branches as selects, and what
fed them for every pixel. The table above is from before those patches; a subset of twelve
of the heavy variants, chosen across its range, now has a mean of 1.02 where it had 1.11.
The 65 heavy pixel shaders of the whole set, timed again with patch 57: a mean of 1.05
where it was 1.09 (17 faster than FXC's build, 11 within 3%, 37 slower; 64 of 65 outputs the
same, the one that differs being the one that differed before). The subset has four of the
nine shaders of the slow family in its twelve, which is why it gained more. A single
shader's figure moves by 5% from one run to the next, and one read 1.81 in that run and
0.94 alone.

Pixel shader output: 248 of 252 the same to 0.1%. Of the four that differ, one
is Unity's UI shader (twice), whose gradient lookup multiplies sampled values
up to 65,000 and uses the result as a texture coordinate, so that a
last-bit difference moves the sample; one agrees with FXC's unoptimised build
and differs from its optimised one; one differs in 0.1% of pixels by 0.003.
None was traced to a wrong instruction, and only the first was traced at all.

Not measured: 46 geometry and tessellation shaders, 27 vertex shaders that
feed those stages, one shader whose inputs the generated vertex shader did not
match, and two pixel shaders that hung the GPU on the made-up inputs (the
harness carries on after a device reset).

One difference from FXC found on the way: for a `switch` whose only label is
`default`, FXC drops the body entirely (the test returned 0 where the source
adds 0.0625); vkd3d executes it. That is left as it is.

## Results

Measured on this machine by `tests/run.py`, `tests/bench.py` and
`tests/features.py`; FXC 10.0.26100 is the reference.

**Correctness.** All 26 test shaders compile (24 directly, one each through
the Slang and DXC routes). The 25 that target SM4+ are accepted by the D3D11
runtime, on WARP and on the hardware GPU (`--gpu`); the SM3 one is only checked
to compile, nothing loads it into D3D9. The 19 pixel shaders with
a render check produce the same image as the FXC build (max channel difference
1.2e-4 on the GPU, float rounding), and the compute shader leaves bit-identical
buffer contents.

**Compile time** (best of 3):

| shader | fxc2 | fxc | speedup | fxc2 insns | fxc insns |
|---|---|---|---|---|---|
| raymarch_ps | 0.03s | 0.08s | 2.8x | 339 | 289 |
| matrix_ps | 0.02s | 0.04s | 1.9x | 161 | 144 |
| blur 7x7 | 0.01s | 0.02s | 1.9x | 76 | 29 |
| blur 31x31 (nested constant loops) | 0.01s | 0.03s | 2.8x | 29 | 29 |
| call chain x8 (generated) | 0.08s | 0.60s | 7.8x | 1417 | 900 |
| call chain x12 (generated) | 3.05s | 106.97s | 35.1x | 9872 | 6386 |

The optimisation passes cost time of their own: the call chain took 0.76 s
before they existed.

**Generated code** in the same micro-benchmark, a 2048 x 2048 fullscreen draw:

| shader | fxc2 code | fxc code | ratio |
|---|---|---|---|
| raymarch_ps | 8.4 ms | 7.2 ms | 1.16x |
| matrix_ps | 6.6 ms | 6.0 ms | 1.10x |
| blur 7x7 | 7.0 ms | 7.9 ms | 0.89x |
| blur 31x31 | 26.5 ms | 26.6 ms | 1.00x |
| call chain x8 | 11.8 ms | 10.4 ms | 1.13x |
| call chain x12 | 187.3 ms | 182.7 ms | 1.03x |

The draw went to the system's default adapter (this laptop has both an Intel
UHD and an RTX 5070; this older script does not pick between them) and is a
single short measurement, so it is coarse. "Speed of the generated code,
shader by shader" above is the better instrument and the larger sample.

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
46. The `l` suffix on floating point literals (`4294967296.0l`), which the preprocessor split
    off as a token of its own. Upstream rvc's shader needs it. The value is still held in
    single precision.
47. **`float - uint` was wrong** (upstream): `a - b` is built as `a + (-b)`, and the negation
    was done in `b`'s type before the conversion, so an unsigned 3 became 4294967293.0.
    ShaderEmu's terminal shader (`at - cell`, a `uint2`) showed it in Unity; it is
    `tests/shaders/terminal_ps.hlsl` now.
48. Conditions are not made booleans first: `if`, `breakc` and `movc` test for "not zero"
    themselves, so an `ine x, 0`, an `ieq x, 0` (the test or the two choices swap), a
    `movc c, 1, 0` or an `and` of a comparison with 1 in front of them goes
    (`VKD3D_SIMPLIFY_CONDITIONS=0` keeps them).
49. **Flag tests are put where the flag was set.** When both sides of a branch leave a
    constant in a variable and the next statement tests it, the tested code moves into the
    places that stored the constant and the test goes. That is what a function returning
    `bool` through early returns turns into once inlined: `if (!step()) break;` was a flag
    written on both paths, copied, and tested twice. `VKD3D_HLSL_THREAD_FLAGS` is the limit
    on the code this may duplicate (64 instructions by default, 0 switches it off).
50. The same pass looks past values nothing uses (an inlined call leaves a load of its
    return value behind), which is what stood between the branch and the test in practice.
51. `refactoringAllowed` is set in the global flags as FXC does (`VKD3D_HLSL_IEEE_STRICT=1`
    leaves it out). No measured effect. Declaring arrays of scalars one component wide, as
    FXC also does, was tried with it and is 3.5% slower on ShaderEmu's tick: not done.
52. **Hexadecimal literals swallowed a closing bracket** (upstream): the preprocessor's rule
    for them took digits up to `f` from `A`, which takes in `[`, `]`, `^` and `_`. In a
    macro's last argument, `xr[(w >> 20) & 0x1f]` never closed its bracket and the macro was
    left unexpanded ("identifier is not declared"). `tests/shaders/macro_hex_ps.hlsl`.
53. A shift and a mask of one word become one `ubfe`, as FXC writes them. Off unless
    `VKD3D_UBFE=1`: on ShaderEmu's tick it changed nothing that could be measured.
54. A branch whose condition is made of uniforms and constants alone is never flattened: the
    GPU takes it the same way for a whole draw (`VKD3D_HLSL_FLATTEN_UNIFORM=1` flattens them
    like any other).
55. When deciding whether a block is small enough to flatten, a sine, cosine, logarithm or
    exponential counts for six operations and a division, square root or reciprocal for
    three. And `sin(x)` and `cos(x)` of one value are one `sincos` with two results, as FXC
    writes them (108 to 65 `sincos` in a Poiyomi variant; FXC: 57; `VKD3D_MERGE_SINCOS=0`).
56. **A lower flattening limit for floating point.** A block that computes in floating point
    is flattened only up to 4 operations (`VKD3D_HLSL_FLATTEN_FLOAT`), integer blocks up to
    10 as before. Material shaders switch effects with `if (feature) colour = effect;`: as a
    select, everything the effect needed is computed for every pixel, and the driver can no
    longer leave it out when the feature is off. One Poiyomi variant went from 1.50 times
    FXC's GPU time to 1.07 by this; twelve heavy variants spread over the earlier results,
    from a mean of 1.11 to 1.03 (the slowest family from 1.40-1.50 to 1.02-1.07), with all
    twelve outputs the same as FXC's. ShaderEmu's tick, which is integer code, is unchanged.
    With the weights of 55 the limit still cannot be higher: at 7 that variant is back at
    1.53. What costs is not what the block computes but what feeds it.
57. Value numbering takes texture samples too (one texture, one sampler, the same
    coordinates: one sample). On Poiyomi's variants it found none to merge at run time: the
    samples the bytecode has more of than FXC's are copies in the two arms of a branch.

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

## Unity: why two DLLs

How to set it up is under "How to use it". The reason for the pair of files:
Unity's `UnityShaderCompiler.exe` does not `LoadLibrary` its
`Data\Tools\D3DCompiler_47.dll`. It maps the file with a private loader, and a
normal MinGW-built DLL crashes it at start-up. `bin/unity/D3DCompiler_47.dll` is
therefore a 6 KB stub with no C runtime and no imports: it finds the real
`kernel32` through the PEB, loads `fxc2_d3dcompiler.dll` from the same folder
with the regular Windows loader, and forwards every call.

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
