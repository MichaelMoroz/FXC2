// profile: vs_5_0
cbuffer PerFrame : register(b0)
{
    float4x4 viewProj;
    float4x4 world;
    float3 lightDir;
    float time;
};

struct VSIn { float3 pos : POSITION; float3 normal : NORMAL; float2 uv : TEXCOORD0; };
struct VSOut { float4 pos : SV_Position; float3 normal : NORMAL; float2 uv : TEXCOORD0; float ndl : TEXCOORD1; };

VSOut main(VSIn i)
{
    VSOut o;
    float4 wp = mul(world, float4(i.pos, 1.0));
    wp.y += sin(time + wp.x) * 0.1;
    o.pos = mul(viewProj, wp);
    o.normal = normalize(mul((float3x3)world, i.normal));
    o.uv = i.uv;
    o.ndl = saturate(dot(o.normal, -lightDir));
    return o;
}
