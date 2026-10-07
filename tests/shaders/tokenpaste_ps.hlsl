// profile: ps_5_0
// render: 128 128 0.6 0
// Token pasting whose result is itself a macro (vkd3d patch 8).
#define SHIFT_RBR 0
#define SHIFT_IER 16
#define GET1(x) ((v >> SHIFT_##x) & 0xff)
#define CAT(a, b) a ## b
#define TWICE(x) ((x) * 2)
#define NAME(n) val_##n
#define PLAIN(n) n##_suffix
float4 main(float4 p : SV_Position) : SV_Target
{
    uint v = (uint)p.x * 65537u;
    float val_3 = 0.25, q_suffix = 0.5;
    return float4(GET1(RBR), GET1(IER), CAT(TWI, CE)(p.y) + NAME(3), PLAIN(q) + CAT(1, 5));
}
