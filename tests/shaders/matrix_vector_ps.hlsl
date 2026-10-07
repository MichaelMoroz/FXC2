// profile: ps_5_0
// render: 128 128 0.6 0 0.3 -0.7 1.1 0.4 0.9 0.2 -0.5 1.3 -1.2 0.6 0.8 -0.1 0.7 1.4 -0.3 0.5 -0.9 0.1 1.2 0.6 0.4 -0.8 0.2 1.0 1.5 -0.4 0.3 0.7 -0.6 0.9 0.5 -1.1 0.8 -0.2 0.6 1.3 -0.7 0.4 1.1 0.2 -0.5 0.9 0.3 -1.0 0.7 0.1 0.6 -0.3 1.2 0.8 -0.9 0.4 0.5 1.0 -0.2 0.7 -0.6 0.3 0.9 1.4 -0.8 0.2 0.6 -0.4 1.1 0.5 0.1 -0.7
// Matrix times vector in every storage order and operand order (vkd3d patch 30).
cbuffer C { float2 resolution; float k; float pad; float4x4 a; row_major float4x4 b; float3x3 c3; row_major float3x4 d34; float4x3 e43; };
float4 main(float4 p : SV_Position) : SV_Target
{
    float2 uv = p.xy / resolution;
    float4 v = float4(uv, k, 1.0);
    float4x4 m = float4x4(1, 2, 3, 4, 0.5, -1, 0.25, 2, uv.x, uv.y, 1, 0, 3, 1, 4, 1.5);
    row_major float3x3 r = float3x3(uv.x, 2, 3, 4, uv.y, 6, 7, 8, 9);
    float4 a1 = mul(m, v) + mul(v, m);
    float3 a2 = mul(r, v.xyz) - mul(v.zyx, r);
    float4 a3 = mul(a, v) + mul(v, a) + mul(b, v) + mul(v, b);
    float3 a4 = mul(c3, v.xyz) + mul(v.xyz, c3) + mul((float3x3)m, v.xyz);
    float3 a5 = mul(d34, v);
    float4 a6 = mul(v.xyz, d34);
    float4 a7 = mul(e43, v.xyz);
    float3 a8 = mul(v, e43);
    return a1 * 0.01 + float4(a2 + a4 + a5 + a8, 0) * 0.02 + a3 + a6 + a7;
}
