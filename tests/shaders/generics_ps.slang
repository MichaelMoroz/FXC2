// profile: ps_5_0
// via: slang
// Slang language features (interfaces, generics, extensions) lowered to plain HLSL.
cbuffer C : register(b0) { float2 resolution; float k; float pad; };

interface IShape { float dist(float2 p); }
struct Circle : IShape { float r; float dist(float2 p) { return length(p) - r; } }
struct Box : IShape { float2 b; float dist(float2 p) { float2 q = abs(p) - b; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0); } }

float shade<T : IShape>(T shape, float2 p) { return smoothstep(0.02, 0.0, shape.dist(p)); }

extension float2 { float2 rotated(float a) { return float2(this.x * cos(a) - this.y * sin(a), this.x * sin(a) + this.y * cos(a)); } }

float4 main(float4 fc : SV_Position) : SV_Target
{
    float2 uv = (fc.xy * 2.0 - resolution) / resolution.y;
    Circle c = { 0.4 };
    Box b = { float2(0.6, 0.1) };
    return float4(shade(c, uv), shade(b, uv.rotated(k)), 0, 1);
}
