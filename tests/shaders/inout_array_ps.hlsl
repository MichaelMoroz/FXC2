// profile: ps_5_0
// render: 128 128 0.6 0
// Arrays passed down as inout arguments through several functions (vkd3d patch 38): worked on
// in place where that cannot be told from copying, and still copied where it can.
cbuffer C { float2 resolution; float k; float pad; };
static uint g_table[8];
uint leaf(inout uint4 c[16], uint i, uint v) { uint o = c[i & 15].x; c[i & 15].x = v; c[(i + 3) & 15].y += o; return o; }
uint mid(inout uint4 c[16], uint i) { uint a = leaf(c, i, i * 3); return a + leaf(c, i + 1, 7); }
// "in" only: what it changes must not come back
uint by_value(uint4 c[16], uint i) { c[i & 15].z = 99; return c[(i + 1) & 15].z + c[i & 15].z; }
// two views of one array: must stay copies
uint two(inout uint a[4], inout uint b[4], uint i) { a[i & 3] += 5; return b[i & 3]; }
// a global passed as an argument and read by name as well
uint with_global(inout uint t[8], uint i) { t[i & 7] = 50; return g_table[i & 7]; }
float4 main(float4 pos : SV_Position) : SV_Target
{
    uint4 cache[16];
    uint2 p = uint2(pos.xy);
    uint n = p.x + p.y * 7;
    [loop] for (uint q = 0; q < 16; q++) cache[q] = uint4(q, q * 2, q + n, 1);
    uint s = 0;
    [loop] for (uint j = 0; j < (p.x & 7); j++) s += mid(cache, j + p.y);
    uint v = by_value(cache, n);
    uint small[4] = { 1, 2, 3, 4 };
    uint w = two(small, small, n);
    [loop] for (uint g = 0; g < 8; g++) g_table[g] = g + 1;
    uint x = with_global(g_table, n);
    uint4 e = cache[n & 15];
    return float4((s & 255) / 255.0, ((e.x + e.y + e.z) & 255) / 255.0, ((v + w * 16 + small[n & 3]) & 255) / 255.0,
            ((x * 16 + g_table[n & 7]) & 255) / 255.0);
}
