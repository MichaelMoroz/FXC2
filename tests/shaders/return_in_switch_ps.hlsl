// profile: ps_5_0
// render: 128 128 0.6 0
// Returns inside switch cases, also within a loop (vkd3d patch 29).
cbuffer C { float2 resolution; float k; float pad; };
float alu(uint op, float a, float b)
{
    switch (op)
    {
        case 0: return a + b;
        case 1: return a - b;
        case 2:
        case 3: if (a > b) return a; return b;
        case 4: { float t = a * b; if (t > 0.3) return t; t += 1.0; return t; }
        case 5: break;
        default: return -1.0;
    }
    return a * 0.5;
}
float mix2(uint op, float a)
{
    float r = a;
    for (uint i = 0; i < 3u; ++i)
    {
        switch (op + i)
        {
            case 1: r += 0.25; break;
            case 2: return r * 2.0;
            case 4: if (r > 1.0) return 9.0; r += 0.5; break;
            default: break;
        }
    }
    return r;
}
float4 main(float4 p : SV_Position) : SV_Target
{
    float2 uv = p.xy / resolution;
    uint op = (uint)p.x % 8u;
    return float4(alu(op, uv.x, uv.y), mix2(op, uv.y), alu((uint)p.y % 7u, uv.y, 0.4), mix2((uint)p.y % 6u, uv.x));
}
