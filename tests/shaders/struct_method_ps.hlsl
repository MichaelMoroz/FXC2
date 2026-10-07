// profile: ps_5_0
// render: 128 128 0.6 0
// Struct member functions (vkd3d patch 44): fields read and written by name, parameters that
// hide a field, overloads, a member calling an earlier member, two structs with the same method
// name. Plus SampleGrad-free checks of state after the calls.
cbuffer C { float2 resolution; float k; float pad; };
struct Decal
{
    float2 scale;
    float mode;
    float4 color;
    void Init(in float4 mask) { color = mode > 0.5 ? mask : 1 - mask; scale = mask.xy * 2; }
    void Scale(float2 by) { scale *= by; }
    void Scale(float by, float mode) { scale *= by + mode; }
    float Weight() { return dot(scale, float2(0.5, 0.25)) + mode; }
    float4 Apply(float4 base, float amount)
    {
        Scale(float2(amount, 1 - amount));
        if (Weight() > 1.0) return lerp(base, color, 0.25);
        return lerp(base, color, saturate(Weight()));
    }
};
struct Ring
{
    float radius;
    float width;
    void Init(float r) { radius = r; width = r * 0.25; }
    float Mask(float2 p) { return saturate(1 - abs(length(p) - radius) / width); }
};
float4 main(float4 pos : SV_Position) : SV_Target
{
    float2 uv = pos.xy / 128.0;
    Decal d;
    d.scale = 0; d.mode = uv.x > 0.5 ? 1 : 0; d.color = 0;
    d.Init(float4(uv, 0.3, 1));
    d.Scale(0.5, 0.25);
    Ring r;
    r.Init(0.3 + 0.1 * d.mode);
    float4 c = d.Apply(float4(0.1, 0.2, 0.3, 1), uv.y);
    c.b += r.Mask(uv - 0.5) * 0.5;
    c.a = d.Weight() * 0.25;
    return c;
}
