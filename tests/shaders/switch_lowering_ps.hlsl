// profile: ps_5_0
// render: 128 128 0.6 0
// Switch shapes lowered to if/else chains unless [forcecase] (vkd3d patch 20).
cbuffer C { float2 resolution; float k; float pad; };
float f(uint t, float a)
{
    float r = a;
    switch (t)
    {
        case 0: r = a * 2.0; break;
        case 1:
        case 2: r = a + 0.25; break;
        case 7:
        default: r = 0.125; break;
        case 3: return 0.5;
        case 4: if (a > 0.5) { r = 1.0; } else { r = 0.0; } break;
        case 5: break;
    }
    return r;
}
float g(uint t, float a)
{
    float r = 0.0;
    [forcecase] switch (t & 3u)
    {
        case 0: r = a; break;
        case 1: if (a > 0.3) break; r = 0.9; break;
        case 2: for (uint i = 0; i < 4u; ++i) { if (i == t) break; r += 0.1; } break;
    }
    switch (t >> 2u)
    {
        case 0: if (a > 0.3) break; r += 0.5; break;
        case 1: r += 0.25; break;
    }
    switch (t) { case 9: case 10: break; case 11: r += 2.0; break; }
    return r;
}
float4 main(float4 p : SV_Position) : SV_Target
{
    float2 uv = p.xy / resolution;
    uint t = (uint)p.x % 13u;
    return float4(f(t, uv.y), g(t, uv.y), f((uint)p.y % 9u, uv.x), g((uint)p.y & 15u, uv.x));
}
