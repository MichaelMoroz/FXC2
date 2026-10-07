// profile: ps_5_0
Texture2D albedo : register(t0);
Texture2D normalMap : register(t1);
TextureCube env : register(t2);
SamplerState linearSampler : register(s0);
SamplerComparisonState shadowSampler : register(s1);
Texture2D shadowMap : register(t3);

cbuffer Material : register(b1)
{
    float4 tint;
    float roughness;
    float metallic;
    int lightCount;
    float4 lights[8];
};

struct PSIn { float4 pos : SV_Position; float3 normal : NORMAL; float2 uv : TEXCOORD0; float ndl : TEXCOORD1; };

float3 fresnel(float3 f0, float c) { return f0 + (1.0 - f0) * pow(1.0 - c, 5.0); }

float4 main(PSIn i, bool front : SV_IsFrontFace) : SV_Target
{
    float4 base = albedo.Sample(linearSampler, i.uv) * tint;
    if (base.a < 0.5) discard;
    float3 n = normalize(i.normal);
    n += normalMap.SampleLevel(linearSampler, i.uv, 0).xyz * 2.0 - 1.0;
    n = normalize(front ? n : -n);
    float3 acc = 0;
    for (int k = 0; k < lightCount; ++k)
    {
        float3 l = normalize(lights[k].xyz);
        float d = saturate(dot(n, l));
        acc += d * lights[k].w * fresnel(lerp(0.04, base.rgb, metallic), d);
    }
    float sh = shadowMap.SampleCmpLevelZero(shadowSampler, i.uv, i.pos.z);
    float3 refl = env.SampleLevel(linearSampler, reflect(float3(0, 0, 1), n), roughness * 8.0).rgb;
    return float4(base.rgb * acc * sh + refl * metallic + ddx(i.uv.x) * 0.0, base.a);
}
