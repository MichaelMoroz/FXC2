// profile: ps_5_0
// render: 128 128 7 0
cbuffer C : register(b0) { float2 resolution; float seed; float pad; };

uint pcg(uint v)
{
    uint state = v * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

float3 palette(int idx)
{
    switch (idx)
    {
        case 0: return float3(1, 0, 0);
        case 1: return float3(0, 1, 0);
        case 2:
        case 3: return float3(0, 0, 1);
        default: return float3(0.5, 0.5, 0.5);
    }
}

float4 main(float4 fc : SV_Position) : SV_Target
{
    uint2 px = (uint2)fc.xy;
    uint h = pcg(px.x + pcg(px.y + (uint)seed));
    int si = (int)px.x - 64;
    int q = si / 7, m = si % 7;
    uint bits = countbits(h) + firstbithigh(h | 1u) + firstbitlow(h | 0x80000000u) + (reversebits(h) & 15u);
    uint sh = (h << (px.x & 31u)) | (h >> ((32u - px.x) & 31u));
    int neg = -si >> 2;
    float3 col = palette((int)(h % 6u));
    uint acc = 0;
    for (uint i = 0; i < (px.y & 15u); ++i)
    {
        if ((i & 1u) == 0u) continue;
        acc += i * i ^ h;
        if (acc > 0xf0000000u) break;
    }
    float f = asfloat((h & 0x007fffffu) | 0x3f800000u) - 1.0;
    return float4(col * f + float3(q, m, neg) * 0.01, (bits + (sh & 255u) + (acc & 1023u) + asuint(f) % 3u) / 1024.0);
}
