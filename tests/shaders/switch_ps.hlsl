// profile: ps_5_0
// render: 128 128 0.6 0
// Stray attributes on statements; switch cases ending in if/else (vkd3d patch 9).
cbuffer C { float2 resolution; float k; float pad; };
float pick(uint t, float a)
{
    switch (t)
    {
        case 0x80000000 + 0: if (a < 0.3) { return 0.25; } else { break; }
        case 1: if (a > 0.5) return 0.5; else break;
        case 2: return 0.75;
        default: break;
    }
    return a;
}
float4 main(float4 p : SV_Position) : SV_Target
{
    float2 uv = p.xy / resolution;
    [branch]
    uint mode = (uint)p.x & 3u;
    if (mode == 3u) mode = 0x80000000u;
    [flatten] float r = pick(mode, uv.y);
    return float4(r, uv, mode & 3u);
}
