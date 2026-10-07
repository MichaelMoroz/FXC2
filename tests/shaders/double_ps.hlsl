// profile: ps_5_0
// render: 128 128 0.6 0
// Scalar double precision, bit-exact against FXC (vkd3d patch 11).
cbuffer C { float2 resolution; float k; float pad; };
float4 main(float4 p : SV_Position) : SV_Target
{
    float t = p.x * 12345.678 + p.y * 3.25 + k;
    double mtime = (double)t * 1000000.0 * 0.1;
    double q = mtime / 4294967296.0;
    float fl = floor((float)q);
    double lo_d = mtime - 4294967296.0 * fl;
    uint lo = (uint)floor((float)lo_d);
    uint hi = (uint)q;
    double acc = (double)lo + (double)(int)p.y * -2.5;
    return float4(lo & 0xffffu, lo >> 16, hi, (float)(acc / 1024.0));
}
