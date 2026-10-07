// profile: ps_5_0
// render: 128 128 0.6 0
// Early returns in ifs, loops, switches and out-parameter functions (vkd3d patch 22).
cbuffer C { float2 resolution; float k; float pad; };
float f1(float a, uint t)
{
    if (t == 0u) return a * 2.0;
    if (t == 1u) { if (a > 0.5) return 0.25; else return 0.75; }
    float r = a + 0.125;
    if (t == 2u) { r *= 3.0; } else { if (a < 0.2) return -1.0; r += 1.0; }
    for (uint i = 0; i < t; ++i) { if (r > 3.0) return r - 10.0; r += 0.5; }
    switch (t) { case 5: return 9.0; case 6: r += 0.25; break; default: break; }
    if (a > 0.9) { r += 4.0; return r; }
    return r;
}
void f2(float a, uint t, out float o)
{
    o = 0.5;
    if (a < 0.1) return;
    o = a;
    if (t > 6u) { o += 1.0; return; }
    else if (t > 3u) { o += 2.0; }
    else return;
    o *= 0.5;
}
float4 main(float4 p : SV_Position) : SV_Target
{
    float2 uv = p.xy / resolution;
    uint t = (uint)p.x % 9u;
    float o; f2(uv.y, t, o);
    if (uv.x > 0.95) return float4(1, 2, 3, 4);
    return float4(f1(uv.y, t), o, f1(uv.x, (uint)p.y % 7u), t);
}
