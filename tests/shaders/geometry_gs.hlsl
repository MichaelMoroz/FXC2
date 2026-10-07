// profile: gs_5_0
struct V { float4 pos : SV_Position; float2 uv : TEXCOORD0; };
cbuffer C : register(b0) { float4x4 vp; float size; };

[maxvertexcount(4)]
void main(point V input[1], inout TriangleStream<V> stream)
{
    static const float2 corners[4] = { float2(-1, -1), float2(-1, 1), float2(1, -1), float2(1, 1) };
    for (int i = 0; i < 4; ++i)
    {
        V o;
        o.pos = mul(vp, input[0].pos + float4(corners[i] * size, 0, 0));
        o.uv = corners[i] * 0.5 + 0.5;
        stream.Append(o);
    }
    stream.RestartStrip();
}
