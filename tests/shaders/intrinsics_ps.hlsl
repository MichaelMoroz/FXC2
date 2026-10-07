// profile: ps_5_0
// render: 128 128 0.75 3
cbuffer C : register(b0) { float2 resolution; float k; float n; };

float4 main(float4 fc : SV_Position) : SV_Target
{
    float2 uv = fc.xy / resolution;
    float2 p = uv * 4.0 - 2.0;
    float3 a = float3(p, k);
    float r = 0;
    r += sin(p.x) * cos(p.y) + tan(p.x * 0.3) + atan2(p.y, p.x) + asin(uv.x) + acos(uv.y) + atan(p.x);
    r += exp(-dot(p, p)) + log(1.0 + uv.x) + log2(1.0 + uv.y) + log10(1.5 + uv.x) + exp2(uv.x);
    r += sqrt(uv.x) + rsqrt(1.0 + uv.y) + pow(uv.x + 0.5, n) + abs(p.x) + sign(p.y);
    r += floor(p.x) + ceil(p.y) + round(p.x * 2.0) + trunc(p.y * 2.0) + frac(p.x * 3.0) + fmod(p.x, 0.7);
    r += lerp(p.x, p.y, uv.x) + smoothstep(0.2, 0.8, uv.x) + step(0.5, uv.y) + clamp(p.x, -1.0, 1.0) + saturate(p.y);
    r += length(a) + distance(a, float3(1, 0, 0)) + dot(a, a.zyx) + min(p.x, p.y) + max(p.x, p.y);
    r += sinh(p.x * 0.5) + cosh(p.y * 0.5) + tanh(p.x) + degrees(uv.x) * 0.01 + radians(p.y * 30.0);
    r += mad(p.x, p.y, k) + rcp(2.0 + uv.x) + ldexp(uv.x, 2.0);
    float3 c = cross(a, float3(0, 1, 0)) + normalize(a) + reflect(a, normalize(float3(1, 1, 0)))
            + refract(normalize(a), float3(0, 0, 1), 0.9) + faceforward(a, float3(0, 0, 1), a);
    float s, co;
    sincos(p.x, s, co);
    float ip;
    float fp = modf(p.y * 2.5, ip);
    bool3 b = a > 0.0;
    float sel = any(b) ? 1.0 : 0.0;
    sel += all(b) ? 1.0 : 0.0;
    sel += isnan(r) ? 100.0 : 0.0;
    return float4(c * 0.1 + r * 0.05, s * co + fp + ip * 0.1 + sel);
}
