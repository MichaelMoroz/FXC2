// profile: ps_3_0
sampler2D tex : register(s0);
float4 tint : register(c0);
float4 main(float2 uv : TEXCOORD0) : COLOR0
{
    float4 c = tex2D(tex, uv) * tint;
    clip(c.a - 0.1);
    return float4(pow(c.rgb, 2.2), c.a);
}
