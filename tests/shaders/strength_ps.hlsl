// profile: ps_5_0
// render: 128 128 0.6 0
// Multiplication and unsigned division by powers of two (vkd3d patch 15).
cbuffer C { float2 resolution; float k; float pad; };
float4 main(float4 p : SV_Position) : SV_Target
{
    uint a = (uint)p.x * 2654435761u + (uint)p.y;
    int b = (int)p.y * 977 - 60000;
    uint2 v = uint2(a, a >> 7);
    uint r0 = a / 64u + a % 2048u + a * 4096u + 8u * a;
    int r1 = b * 16 + b / 4 + b % 8;
    uint2 r2 = v / uint2(2u, 16u) + v % 32u + v * uint2(4u, 2u);
    uint r3 = a / 10u + a % 7u + a * 3u + 64u / (a | 1u);
    return float4(r0 & 0xffffu, r1, (r2.x ^ r2.y) & 0xffffu, r3 & 0xffffu);
}
