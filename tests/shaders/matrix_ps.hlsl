// profile: ps_5_0
// render: 128 128 0.6 2
cbuffer C : register(b0) { float2 resolution; float angle; float scale; };

struct Ray { float3 o; float3 d; };
struct Hit { float t; float3 n; int id; };

float3x3 rot(float3 axis, float a)
{
    float s = sin(a), c = cos(a), ic = 1.0 - c;
    return float3x3(
        ic * axis.x * axis.x + c, ic * axis.x * axis.y - axis.z * s, ic * axis.z * axis.x + axis.y * s,
        ic * axis.x * axis.y + axis.z * s, ic * axis.y * axis.y + c, ic * axis.y * axis.z - axis.x * s,
        ic * axis.z * axis.x - axis.y * s, ic * axis.y * axis.z + axis.x * s, ic * axis.z * axis.z + c);
}

bool sphere(Ray r, float3 c, float rad, inout Hit h, int id)
{
    float3 oc = r.o - c;
    float b = dot(oc, r.d), cc = dot(oc, oc) - rad * rad, disc = b * b - cc;
    if (disc < 0.0) return false;
    float t = -b - sqrt(disc);
    if (t < 0.0 || t > h.t) return false;
    h.t = t; h.n = normalize(oc + r.d * t); h.id = id;
    return true;
}

float4 main(float4 fc : SV_Position) : SV_Target
{
    float2 uv = (fc.xy * 2.0 - resolution) / resolution.y;
    float3x3 m = mul(rot(normalize(float3(1, 2, 3)), angle), rot(float3(0, 1, 0), angle * 2.0));
    float4x4 big = float4x4(float4(m[0], 0), float4(m[1], 0), float4(m[2], 0), float4(0, 0, 0, 1));
    big = transpose(big);
    float det = determinant(m);
    Ray r;
    r.o = mul(big, float4(0, 0, -3, 1)).xyz;
    r.d = mul(normalize(float3(uv, 1.2)), m);
    static const float3 centers[4] = { float3(0, 0, 0), float3(1, 0.5, 0), float3(-1, -0.5, 0.5), float3(0, 1, -0.5) };
    float radii[4];
    radii[0] = 0.6 * scale; radii[1] = 0.3; radii[2] = 0.4; radii[3] = 0.25 * scale;
    Hit h;
    h.t = 1e9; h.n = 0; h.id = -1;
    int hits = 0;
    for (int i = 0; i < 4; ++i)
        hits += sphere(r, centers[i], radii[i], h, i) ? 1 : 0;
    float3 col = h.id < 0 ? float3(uv * 0.5 + 0.5, det) : (h.n * 0.5 + 0.5) * (1.0 - h.id * 0.2);
    float2x2 m2 = float2x2(m[0].xy, m[1].xy);
    col.xy = mul(m2, col.xy) * 0.5 + 0.25;
    return float4(col, hits * 0.25 + m._m12);
}
