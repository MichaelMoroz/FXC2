"""Probes which HLSL features fxc2 (vkd3d-shader) compiles, one small shader
per feature, and prints a support matrix. fxc.exe is run on the same snippet
so a failure of both means the probe itself is wrong.

Usage: python tests/features.py [--markdown]
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from run import FXC2, find_fxc  # noqa: E402
import d3d11  # noqa: E402

PS = "float4 main(float4 p : SV_Position, float2 uv : TEXCOORD0) : SV_Target { %s }"
CS = "[numthreads(4, 4, 1)] void main(uint3 id : SV_DispatchThreadID) { %s }"

# (category, feature, profile, source)
PROBES = [
    ("language", "struct methods", "ps_5_0", "struct S { float a; float get() { return a * 2; } };\n" + PS % "S s; s.a = uv.x; return s.get();"),
    ("language", "function overloading", "ps_5_0", "float f(float a) { return a; } float f(float2 a) { return a.x + a.y; }\n" + PS % "return f(uv) + f(uv.x);"),
    ("language", "out / inout params", "ps_5_0", "void f(in float a, out float b, inout float c) { b = a; c += a; }\n" + PS % "float b, c = 1; f(uv.x, b, c); return b + c;"),
    ("language", "switch", "ps_5_0", PS % "switch ((int)p.x & 3) { case 0: return 0; case 1: return 1; default: return 2; }"),
    ("language", "while / do-while", "ps_5_0", PS % "float a = 0; int i = 0; while (i < 3) { a += uv.x; ++i; } do { a *= 2; } while (a < 1); return a;"),
    ("language", "early return in loop", "ps_5_0", PS % "for (int i = 0; i < 8; ++i) { if (uv.x * i > 2) return i; } return 0;"),
    ("language", "arrays of structs", "ps_5_0", "struct L { float3 c; float i; }; cbuffer C { L lights[4]; };\n" + PS % "float3 a = 0; for (int i = 0; i < 4; ++i) a += lights[i].c * lights[i].i; return float4(a, 1);"),
    ("language", "static const arrays", "ps_5_0", "static const float w[3] = { 0.25, 0.5, 0.25 };\n" + PS % "return w[(int)p.x % 3];"),
    ("language", "typedef / #define", "ps_5_0", "typedef float3 color;\n#define TWO(x) ((x) * 2)\n" + PS % "color c = TWO(uv.xyx); return float4(c, 1);"),
    ("language", "matrix swizzles (_m00)", "ps_5_0", "float4x4 m;\n" + PS % "return float4(m._m00, m._12, m[2][1], m._m33_m32.x);"),
    ("language", "row_major / column_major", "ps_5_0", "row_major float4x4 a; column_major float4x4 b;\n" + PS % "return mul(a, p) + mul(b, p);"),
    ("language", "interfaces / classes", "ps_5_0", "interface I { float f(); }; class A : I { float v; float f() { return v; } }; A a;\n" + PS % "return a.f();"),
    ("language", "namespaces", "ps_5_0", "namespace N { float f(float a) { return a * 2; } }\n" + PS % "return N::f(uv.x);"),
    ("language", "struct inheritance", "ps_5_0", "struct A { float a; }; struct B : A { float b; };\n" + PS % "B v; v.a = uv.x; v.b = uv.y; return v.a + v.b;"),
    ("language", "nested structs + init lists", "ps_5_0", "struct A { float2 a; float b; }; struct B { A x; float4 y; };\n" + PS % "B v = { { uv, 1 }, p }; return v.x.b + v.y;"),
    ("language", "double", "ps_5_0", PS % "double d = uv.x; d = d * d + 1.0; return (float)d;"),
    ("language", "min16float / half", "ps_5_0", PS % "min16float a = uv.x; half b = uv.y; return a + b;"),
    ("language", "uniform params on entry", "ps_5_0", "float4 main(float4 p : SV_Position, uniform float k) : SV_Target { return k; }"),
    ("language", "[unroll] / [loop] / [branch] / [flatten]", "ps_5_0", PS % "float a = 0; [unroll] for (int i = 0; i < 4; ++i) a += i; [branch] if (uv.x > 0) a++; [flatten] if (uv.y > 0) a--; return a;"),
    ("language", "templates (HLSL 2021)", "ps_5_0", "template<typename T> T sq(T x) { return x * x; }\n" + PS % "return sq(uv.x);"),
    ("language", "operator overloading (HLSL 2021)", "ps_5_0", "struct C { float r; C operator+(C o) { C x; x.r = r + o.r; return x; } };\n" + PS % "C a, b; a.r = 1; b.r = 2; return (a + b).r;"),

    ("intrinsics", "trig / exp / pow family", "ps_5_0", PS % "return sin(uv.x) + cos(uv.y) + tan(uv.x) + atan2(uv.y, uv.x) + exp(uv.x) + log(uv.x + 1) + pow(uv.x, 2.2) + sqrt(uv.y);"),
    ("intrinsics", "hyperbolic / inverse trig", "ps_5_0", PS % "return sinh(uv.x) + cosh(uv.y) + tanh(uv.x) + asin(uv.x) + acos(uv.y) + atan(uv.x);"),
    ("intrinsics", "lerp / smoothstep / step / clamp", "ps_5_0", PS % "return lerp(uv.x, uv.y, 0.5) + smoothstep(0, 1, uv.x) + step(0.5, uv.y) + clamp(uv.x, 0.2, 0.8);"),
    ("intrinsics", "vector (dot/cross/normalize/reflect/refract)", "ps_5_0", PS % "float3 a = uv.xyx; return float4(cross(a, a.zxy) + normalize(a) + reflect(a, a.yzx) + refract(a, a.yzx, 0.5), dot(a, a) + length(a) + distance(a, a.zyx));"),
    ("intrinsics", "matrix (mul/transpose/determinant)", "ps_5_0", "float3x3 m;\n" + PS % "return float4(mul(transpose(m), uv.xyx), determinant(m));"),
    ("intrinsics", "any / all / isnan / isinf / isfinite", "ps_5_0", PS % "return any(uv > 0) + all(uv > 0) + isnan(uv.x) + isinf(uv.y) + isfinite(uv.x);"),
    ("intrinsics", "fmod / modf / frexp / ldexp", "ps_5_0", PS % "float i, e; float f = modf(uv.x * 3, i); float m = frexp(uv.y + 1, e); return fmod(uv.x, 0.3) + f + i + m + e + ldexp(uv.x, 2);"),
    ("intrinsics", "ddx / ddy / fwidth (+coarse/fine)", "ps_5_0", PS % "return ddx(uv.x) + ddy(uv.y) + fwidth(uv.x) + ddx_fine(uv.x) + ddy_coarse(uv.y);"),
    ("intrinsics", "clip / discard", "ps_5_0", PS % "clip(uv.x - 0.5); if (uv.y < 0.1) discard; return 1;"),
    ("intrinsics", "asfloat / asint / asuint", "ps_5_0", PS % "uint u = asuint(uv.x); int i = asint(uv.y); return asfloat(u ^ (uint)i);"),
    ("intrinsics", "countbits / firstbithigh / firstbitlow / reversebits", "ps_5_0", PS % "uint u = (uint)p.x; return countbits(u) + firstbithigh(u) + firstbitlow(u) + reversebits(u);"),
    ("intrinsics", "f16tof32 / f32tof16", "ps_5_0", PS % "return f16tof32(f32tof16(uv.x));"),
    ("intrinsics", "mad / rcp / saturate / sign / trunc / round", "ps_5_0", PS % "return mad(uv.x, uv.y, 1) + rcp(uv.x + 1) + saturate(uv.y) + sign(uv.x) + trunc(uv.x * 4) + round(uv.y * 4);"),
    ("intrinsics", "D3DCOLORtoUBYTE4 / lit / dst", "ps_5_0", PS % "return lit(uv.x, uv.y, 8) + dst(p, p) + D3DCOLORtoUBYTE4(p);"),
    ("intrinsics", "dot on ints", "ps_5_0", PS % "int2 a = int2(p.xy); return dot(a, a);"),
    ("intrinsics", "EvaluateAttribute* / GetRenderTargetSample*", "ps_5_0", "float4 main(float4 p : SV_Position, float2 uv : TEXCOORD0) : SV_Target { return EvaluateAttributeCentroid(uv).xyxy + GetRenderTargetSampleCount(); }"),

    ("textures", "Sample / SampleLevel / SampleBias / SampleGrad", "ps_5_0", "Texture2D t; SamplerState s;\n" + PS % "return t.Sample(s, uv) + t.SampleLevel(s, uv, 1) + t.SampleBias(s, uv, 0.5) + t.SampleGrad(s, uv, ddx(uv), ddy(uv));"),
    ("textures", "Sample with offset", "ps_5_0", "Texture2D t; SamplerState s;\n" + PS % "return t.Sample(s, uv, int2(1, -1));"),
    ("textures", "SampleCmp / SampleCmpLevelZero", "ps_5_0", "Texture2D t; SamplerComparisonState s;\n" + PS % "return t.SampleCmp(s, uv, 0.5) + t.SampleCmpLevelZero(s, uv, 0.5);"),
    ("textures", "Gather / GatherRed / GatherCmp", "ps_5_0", "Texture2D t; SamplerState s; SamplerComparisonState c;\n" + PS % "return t.Gather(s, uv) + t.GatherGreen(s, uv, int2(1, 0)) + t.GatherCmp(c, uv, 0.5);"),
    ("textures", "Load / operator[]", "ps_5_0", "Texture2D t;\n" + PS % "return t.Load(int3(p.xy, 0)) + t[uint2(p.xy)];"),
    ("textures", "GetDimensions", "ps_5_0", "Texture2D t;\n" + PS % "uint w, h, l; t.GetDimensions(0, w, h, l); return w + h + l;"),
    ("textures", "CalculateLevelOfDetail", "ps_5_0", "Texture2D t; SamplerState s;\n" + PS % "return t.CalculateLevelOfDetail(s, uv);"),
    ("textures", "Texture2DArray / 3D / Cube / CubeArray", "ps_5_0", "Texture2DArray a; Texture3D b; TextureCube c; TextureCubeArray d; SamplerState s;\n" + PS % "return a.Sample(s, uv.xyx) + b.Sample(s, uv.xyx) + c.Sample(s, uv.xyx) + d.Sample(s, uv.xyxy);"),
    ("textures", "Texture2DMS Load + sample count", "ps_5_0", "Texture2DMS<float4> t;\n" + PS % "uint w, h, n; t.GetDimensions(w, h, n); return t.Load(int2(p.xy), 1) + n;"),
    ("textures", "typed textures <uint> / <int4>", "ps_5_0", "Texture2D<uint> a; Texture2D<int4> b;\n" + PS % "return a.Load(int3(p.xy, 0)) + b.Load(int3(p.xy, 0)).x;"),
    ("textures", "arrays of textures", "ps_5_0", "Texture2D t[4]; SamplerState s;\n" + PS % "return t[0].Sample(s, uv) + t[3].Sample(s, uv);"),
    ("textures", "SM3 tex2D / texCUBE / tex2Dlod", "ps_3_0", "sampler2D a; samplerCUBE b;\nfloat4 main(float2 uv : TEXCOORD0) : COLOR { return tex2D(a, uv) + texCUBE(b, uv.xyx) + tex2Dlod(a, uv.xyxy); }"),
    ("textures", "legacy tex2D on SM4 (fxc needs /Gec)", "ps_4_0", "sampler2D a;\nfloat4 main(float2 uv : TEXCOORD0) : SV_Target { return tex2D(a, uv); }"),

    ("buffers", "cbuffer + packoffset + register", "ps_5_0", "cbuffer C : register(b2) { float4 a : packoffset(c1); float b : packoffset(c0.y); };\n" + PS % "return a + b;"),
    ("buffers", "ConstantBuffer<T> (SM5.1)", "ps_5_1", "struct S { float4 a; }; ConstantBuffer<S> cb : register(b0);\n" + PS % "return cb.a;"),
    ("buffers", "Buffer<T> Load", "ps_5_0", "Buffer<float4> b;\n" + PS % "return b.Load((int)p.x) + b[(uint)p.y];"),
    ("buffers", "StructuredBuffer operator[]", "ps_5_0", "struct S { float4 a; uint b; }; StructuredBuffer<S> sb;\n" + PS % "return sb[(uint)p.x].a * sb[1].b;"),
    ("buffers", "StructuredBuffer.Load", "ps_5_0", "struct S { float4 a; }; StructuredBuffer<S> sb;\n" + PS % "return sb.Load((int)p.x).a;"),
    ("buffers", "StructuredBuffer.GetDimensions", "ps_5_0", "StructuredBuffer<float4> sb;\n" + PS % "uint n, s; sb.GetDimensions(n, s); return n + s;"),
    ("buffers", "ByteAddressBuffer Load/Load2-4", "ps_5_0", "ByteAddressBuffer b;\n" + PS % "return b.Load(0) + b.Load2(4).x + b.Load3(12).x + b.Load4(24).x;"),

    ("compute", "RWTexture2D read/write", "cs_5_0", "RWTexture2D<float4> t;\n" + CS % "t[id.xy] = t[id.xy] * 2;"),
    ("compute", "RWTexture2D.GetDimensions", "cs_5_0", "RWTexture2D<float4> t;\n" + CS % "uint w, h; t.GetDimensions(w, h); t[id.xy] = w + h;"),
    ("compute", "RWTexture3D / RWTexture2DArray", "cs_5_0", "RWTexture3D<float> a; RWTexture2DArray<float4> b;\n" + CS % "a[id] = 1; b[id] = 2;"),
    ("compute", "RWStructuredBuffer read/write", "cs_5_0", "struct P { float3 pos; float life; }; RWStructuredBuffer<P> b;\n" + CS % "P p = b[id.x]; p.life -= 1; b[id.x] = p; b[id.y].pos.x = 3;"),
    ("compute", "RWStructuredBuffer counter", "cs_5_0", "RWStructuredBuffer<uint> b;\n" + CS % "uint i = b.IncrementCounter(); b[i] = id.x;"),
    ("compute", "Append / ConsumeStructuredBuffer", "cs_5_0", "AppendStructuredBuffer<uint> a; ConsumeStructuredBuffer<uint> c;\n" + CS % "a.Append(c.Consume());"),
    ("compute", "RWBuffer<uint>", "cs_5_0", "RWBuffer<uint> b;\n" + CS % "b[id.x] = b[id.y] + 1;"),
    ("compute", "RWByteAddressBuffer Store*", "cs_5_0", "RWByteAddressBuffer b;\n" + CS % "uint o = (id.x + id.y * 64) * 32; b.Store(o, id.x); b.Store2(o + 4, id.xy); b.Store4(o + 16, id.xyzz);"),
    ("compute", "RWByteAddressBuffer Load*", "cs_5_0", "RWByteAddressBuffer b;\n" + CS % "uint o = (id.x + id.y * 64) * 16; b.Store(o, b.Load(o + 4) + b.Load2(o + 8).y);"),
    ("compute", "InterlockedAdd on RWTexture / RWBuffer", "cs_5_0", "RWTexture2D<uint> t; RWBuffer<uint> b;\n" + CS % "uint o; InterlockedAdd(t[id.xy], 1, o); InterlockedMax(b[id.x], o);"),
    ("compute", "InterlockedAdd on RWStructuredBuffer", "cs_5_0", "RWStructuredBuffer<uint> b;\n" + CS % "InterlockedAdd(b[id.x], 1);"),
    ("compute", "RWByteAddressBuffer.Interlocked*", "cs_5_0", "RWByteAddressBuffer b;\n" + CS % "uint o; b.InterlockedAdd(0, 1, o);"),
    ("compute", "groupshared + GroupMemoryBarrier", "cs_5_0", "groupshared float g[16];\n[numthreads(4, 4, 1)] void main(uint gi : SV_GroupIndex) { g[gi] = gi; GroupMemoryBarrierWithGroupSync(); g[gi] += g[15 - gi]; }"),
    ("compute", "SV_GroupID / SV_GroupThreadID", "cs_5_0", "RWBuffer<uint> b;\n[numthreads(4, 4, 1)] void main(uint3 g : SV_GroupID, uint3 t : SV_GroupThreadID) { b[g.x * 16 + t.y * 4 + t.x] = t.y; }"),
    ("compute", "cs_4_0 (D3D10 compute)", "cs_4_0", "RWStructuredBuffer<uint> b;\n" + CS % "b[id.x] = id.y;"),

    ("stages", "vertex shader + SV_VertexID/InstanceID", "vs_5_0", "float4 main(float3 p : POSITION, uint v : SV_VertexID, uint i : SV_InstanceID) : SV_Position { return float4(p, v + i); }"),
    ("stages", "geometry shader (TriangleStream)", "gs_5_0", "struct V { float4 p : SV_Position; };\n[maxvertexcount(3)] void main(triangle V i[3], inout TriangleStream<V> s) { for (int k = 0; k < 3; ++k) s.Append(i[k]); s.RestartStrip(); }"),
    ("stages", "geometry shader instancing + SV_RenderTargetArrayIndex", "gs_5_0", "struct V { float4 p : SV_Position; uint l : SV_RenderTargetArrayIndex; };\n[instance(6)] [maxvertexcount(3)] void main(triangle float4 i[3] : SV_Position, uint id : SV_GSInstanceID, inout TriangleStream<V> s) { for (int k = 0; k < 3; ++k) { V o; o.p = i[k]; o.l = id; s.Append(o); } }"),
    ("stages", "hull shader", "hs_5_0", "struct C { float3 p : POS; }; struct K { float e[3] : SV_TessFactor; float i : SV_InsideTessFactor; };\nK pc(InputPatch<C, 3> p) { K k; k.e[0] = k.e[1] = k.e[2] = 4; k.i = 4; return k; }\n[domain(\"tri\")] [partitioning(\"fractional_odd\")] [outputtopology(\"triangle_cw\")] [outputcontrolpoints(3)] [patchconstantfunc(\"pc\")]\nC main(InputPatch<C, 3> p, uint i : SV_OutputControlPointID) { return p[i]; }"),
    ("stages", "domain shader", "ds_5_0", "struct C { float3 p : POS; }; struct K { float e[3] : SV_TessFactor; float i : SV_InsideTessFactor; };\n[domain(\"tri\")] float4 main(K k, float3 b : SV_DomainLocation, const OutputPatch<C, 3> p) : SV_Position { return float4(p[0].p * b.x + p[1].p * b.y + p[2].p * b.z, 1); }"),
    ("stages", "pixel: MRT + SV_Depth + SV_Coverage", "ps_5_0", "struct O { float4 a : SV_Target0; float4 b : SV_Target1; float d : SV_Depth; uint c : SV_Coverage; };\nO main(float4 p : SV_Position, uint cov : SV_Coverage, uint s : SV_SampleIndex) { O o; o.a = p; o.b = s; o.d = 0.5; o.c = cov; return o; }"),
    ("stages", "pixel: SV_IsFrontFace / SV_PrimitiveID / nointerpolation", "ps_5_0", "float4 main(bool f : SV_IsFrontFace, uint id : SV_PrimitiveID, nointerpolation float4 c : COLOR, centroid float2 uv : TEXCOORD) : SV_Target { return f ? c : id + uv.x; }"),
    ("stages", "SV_ClipDistance / SV_CullDistance", "vs_5_0", "struct O { float4 p : SV_Position; float2 c : SV_ClipDistance0; float k : SV_CullDistance0; };\nO main(float4 p : POSITION) { O o; o.p = p; o.c = p.xy; o.k = p.z; return o; }"),
    ("stages", "SM2 vertex + pixel", "vs_2_0", "float4x4 wvp;\nfloat4 main(float4 p : POSITION) : POSITION { return mul(p, wvp); }"),
    ("stages", "effects (fx_5_0 technique)", "fx_5_0", "float4 PS() : SV_Target { return 1; }\ntechnique11 T { pass P { SetPixelShader(CompileShader(ps_5_0, PS())); } }"),
]


HLSL2DXBC = os.path.join(ROOT, "tools", "hlsl2dxbc.py")
ROUTES = ("direct", "slang", "dxc")


def compile_with(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def first_error(msg):
    lines = [l for l in msg.splitlines() if ": E" in l or "error" in l.lower()]
    return (lines[0].split(": ", 1)[-1] if lines else (msg.splitlines() or [""])[0])[:100]


def main():
    markdown = "--markdown" in sys.argv
    out = os.path.join(ROOT, "out", "features")
    os.makedirs(out, exist_ok=True)
    fxc = find_fxc()
    dev = d3d11.Device()
    rows, last_cat = [], None
    passed = dict.fromkeys(ROUTES, 0)
    any_route = 0
    for n, (cat, name, profile, source) in enumerate(PROBES):
        src = os.path.join(out, "probe%02d.hlsl" % n)
        obj = os.path.join(out, "probe%02d.dxbc" % n)
        with open(src, "w") as f:
            f.write(source + "\n")
        # The front ends of the indirect routes only speak SM4+ shader stages.
        # SM5.1 is D3D12-only, so the D3D11 runtime cannot vouch for it.
        modern = profile[0] != "f" and int(profile[3]) >= 4
        results, note = {}, ""
        for route in ROUTES:
            if route != "direct" and not modern:
                results[route] = None
                continue
            if os.path.exists(obj):
                os.remove(obj)
            if route == "direct":
                ok, msg = compile_with([FXC2, "-T", profile, "-Fo", obj, src])
            else:
                ok, msg = compile_with([sys.executable, HLSL2DXBC, "--via", route, "-T", profile, "-Fo", obj, src])
            if ok and modern and not profile.endswith("5_1"):
                hr = dev.check(profile[:2], open(obj, "rb").read())
                if hr:
                    ok, msg = False, "error: D3D11 rejects output (0x%08x)" % hr
            if not ok and route == "direct":
                note = first_error(msg)
            results[route] = ok
            passed[route] += ok
        any_route += any(results.values())
        ref = compile_with([fxc, "/nologo", "/T", profile, "/Fo", obj + ".ref", src])[0] if fxc else None
        rows.append((cat, name, profile, results, ref, note))

    def mark(v):
        return "-" if v is None else "yes" if v else "NO"

    for cat, name, profile, results, ref, note in rows:
        marks = [mark(results[r]) for r in ROUTES] + [mark(ref).lower()]
        if markdown:
            if cat != last_cat:
                print("\n**%s**\n" % cat)
                print("| feature | profile | direct | slang | dxc | fxc | direct route error |")
                print("|---|---|---|---|---|---|---|")
            print("| %s | %s | %s | %s | %s | %s | %s |" % (
                (name, profile) + tuple(marks) + (note.replace("|", "/"),)))
        else:
            if cat != last_cat:
                print("\n[%s]%s direct slang dxc  fxc" % (cat, " " * (60 - len(cat))))
            print("  %-52s %-7s  %-6s %-5s %-4s %-3s %s" % ((name, profile) + tuple(marks) + (note,)))
        last_cat = cat
    print("\n%d probes: direct %d, slang %d, dxc %d, at least one route %d" % (
        len(PROBES), passed["direct"], passed["slang"], passed["dxc"], any_route))


if __name__ == "__main__":
    main()
