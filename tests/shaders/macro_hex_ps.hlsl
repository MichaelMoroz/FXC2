// profile: ps_5_0
// A hexadecimal literal before a closing bracket in a macro's last argument: vkd3d's
// preprocessor read "0x1f]" as one number (its digits ran to 'f' from 'A', which takes in the
// bracket), never saw the bracket close and left the macro unexpanded. ShaderEmu's
// mem_set_ram(addr, xr[(w >> 20) & 0x1f], mask) showed it.
static uint xr[32];

uint sum3(uint q, uint a, uint b, uint c)
{
    return a + b + c + q;
}

#define FIRST 7,
#define g(a0, a1, a2) sum3(FIRST a0, a1, a2)

float4 main(float4 pos : SV_Position) : SV_Target
{
    uint w = (uint)pos.x + 64u * (uint)pos.y;
    uint i;

    for (i = 0; i < 32; ++i)
        xr[i] = i * 3u + (w & 7u);
    uint r = g((w & 0x7ff0) | (w & 0xc), 1u, xr[(w >> 2) & 0x1f]);
    return float4((r & 0xff) / 255.0, ((r >> 8) & 0xff) / 255.0, xr[0x1f] / 255.0, 1.0);
}
