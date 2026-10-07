// profile: ps_4_0
Texture2D tex; SamplerState smp;
float4 weights[4];
float4 main(float2 uv : TEXCOORD0, float4 col : COLOR0) : SV_Target
{
    float4 acc = 0;
    for (int i = 0; i < 4; ++i)
        acc += tex.Sample(smp, uv + i * 0.01) * weights[i];
    return acc * col;
}
