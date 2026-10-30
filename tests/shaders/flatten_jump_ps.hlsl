// profile: ps_5_0
// render: 128 128 0.6 0
// [flatten] on a branch that leaves a loop stays a branch, as under FXC (vkd3d patch 67): a return in a
// loop is a break by then. Unity's ScreenSpaceReflections has this shape.
cbuffer C { float2 resolution; float k; float pad; };

float march(float2 uv)
{
    float z = uv.x;
    for (int i = 0; i < 16; ++i)
    {
        z += uv.y * 0.125;
        [flatten]
        if (z > k + 0.25)
            return z - float(i) / 16.0;
        [flatten]
        if (z < 0.0625)
        {
            [branch]
            if (uv.y < 0.5)
                break;
            z += 0.25;
        }
    }
    return z * 0.5;
}

float4 main(float4 pos : SV_Position) : SV_Target
{
    float2 uv = pos.xy / resolution;
    return float4(march(uv), uv.x, uv.y, 1.0);
}
