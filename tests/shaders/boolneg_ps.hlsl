// profile: ps_5_0
// render: 128 128 0.6 0
// float - bool and -bool: negating a bool yields an int (vkd3d patch 5).
cbuffer C { float2 resolution; float k; float pad; };
float4 main(float4 p : SV_Position) : SV_Target
{
    float2 uv = p.xy / resolution;
    bool b = uv.x > 0.5;
    bool2 b2 = uv > k;
    float a = 2.0 - b;
    float2 c = uv - b2;
    int n = -b;
    float d = 1.0; d -= (uv.y > 0.25);
    return float4(a, c, n + d * 0.5);
}
