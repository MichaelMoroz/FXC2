// profile: ps_5_0
// Shadertoy-style: the kind of loop/branch heavy shader FXC is slow on.
cbuffer C : register(b0) { float2 resolution; float time; float pad; };

float sdBox(float3 p, float3 b) { float3 q = abs(p) - b; return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0); }
float3x3 rotY(float a) { float s = sin(a), c = cos(a); return float3x3(c, 0, s, 0, 1, 0, -s, 0, c); }

float map(float3 p)
{
    float d = 1e9;
    float s = 1.0;
    for (int i = 0; i < 5; ++i)
    {
        p = mul(rotY(time * 0.1 + i), p);
        p = abs(p) - 0.6 * s;
        d = min(d, sdBox(p, float3(0.3, 0.3, 0.3) * s));
        s *= 0.55;
    }
    return d;
}

float3 calcNormal(float3 p)
{
    float2 e = float2(0.001, 0);
    return normalize(float3(map(p + e.xyy) - map(p - e.xyy), map(p + e.yxy) - map(p - e.yxy), map(p + e.yyx) - map(p - e.yyx)));
}

float4 main(float4 fragCoord : SV_Position) : SV_Target
{
    float2 uv = (fragCoord.xy * 2.0 - resolution) / resolution.y;
    float3 ro = float3(0, 0, -4), rd = normalize(float3(uv, 1.5));
    float t = 0;
    float3 col = 0;
    for (int i = 0; i < 96; ++i)
    {
        float3 p = ro + rd * t;
        float d = map(p);
        if (d < 0.001)
        {
            float3 n = calcNormal(p);
            float ao = 1.0;
            for (int j = 1; j <= 5; ++j)
                ao -= (j * 0.05 - map(p + n * j * 0.05)) / exp2((float)j);
            col = (0.5 + 0.5 * n) * saturate(ao);
            break;
        }
        t += d;
        if (t > 20.0) break;
    }
    return float4(col, 1);
}
