// profile: ps_5_0
// render: 128 128 0.6 0
// The high half of a 32 x 32 bit product: mulhi(), umulExtended() and imulExtended() with fxc2
// (vkd3d patch 42), the long way round with FXC. Both must render the same.
cbuffer C { float2 resolution; float k; float pad; };
uint mulhu_ref(uint a, uint b)
{
    uint a0 = a & 0xffff, a1 = a >> 16, b0 = b & 0xffff, b1 = b >> 16;
    uint p00 = a0 * b0, p01 = a0 * b1, p10 = a1 * b0, p11 = a1 * b1;
    uint mid = (p00 >> 16) + (p01 & 0xffff) + (p10 & 0xffff);
    return p11 + (p01 >> 16) + (p10 >> 16) + (mid >> 16);
}
uint mulhs_ref(uint a, uint b) { return mulhu_ref(a, b) - ((a >> 31) ? b : 0) - ((b >> 31) ? a : 0); }
float4 main(float4 pos : SV_Position) : SV_Target
{
    uint2 p = uint2(pos.xy);
    uint a = p.x * 0x9E3779B1u + 0x12345u, b = p.y * 0x85EBCA6Bu ^ 0xdeadbeefu;
    uint hu, lu, hs, ls, h1;
    uint2 hv;
#ifdef __FXC2__
    umulExtended(a, b, hu, lu);
    int shi, slo;
    imulExtended(int(a), int(b), shi, slo);
    hs = uint(shi); ls = uint(slo);
    h1 = mulhi(a, 0x10001u);
    hv = mulhi(uint2(a, b), uint2(b, 77u));
#else
    hu = mulhu_ref(a, b); lu = a * b;
    hs = mulhs_ref(a, b); ls = a * b;
    h1 = mulhu_ref(a, 0x10001u);
    hv = uint2(mulhu_ref(a, b), mulhu_ref(b, 77u));
#endif
    uint x = hu ^ (hu >> 13), y = hs ^ (hs >> 9), z = lu ^ ls ^ h1, w = hv.x + hv.y;
    return float4((x & 255) / 255.0, (y & 255) / 255.0, ((z ^ (z >> 16)) & 255) / 255.0, (w & 255) / 255.0);
}
