// profile: ps_4_0
// render: 128 128 0.6 0
// firstbithigh/firstbitlow emulated under shader model 4 (vkd3d patch 6).
cbuffer C { float2 resolution; float k; float pad; };
float4 main(float4 p : SV_Position) : SV_Target
{
    uint u = (uint)p.x * 2654435761u * ((uint)p.y + 1u);
    if (((uint)p.x & 7u) == 0u) u = 0u;
    int i = (int)u >> ((uint)p.y & 15u);
    uint2 v = uint2(u >> 3, u << 5);
    return float4((int)firstbithigh(u), (int)firstbitlow(u), (int)firstbithigh(i), (int)firstbithigh(v).x + (int)firstbitlow(v).y * 64);
}
