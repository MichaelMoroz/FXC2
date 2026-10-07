// profile: ps_5_0
// render: 128 128 0.6 0
// ShaderEmu's character terminal (Terminal.shader), which rendered wrongly in Unity with fxc2:
// a constant array indexed at run time, unsigned division and modulus, casts of float vectors
// to uint, Load, and a sample with explicit gradients. The grid and the glyph atlas are made
// from the pixel position here, since the test has no textures.
cbuffer C { float2 resolution; float k; float pad; };

static const float3 Palette[16] = {
    float3(0.035, 0.04, 0.05), float3(0.80, 0.25, 0.25), float3(0.45, 0.78, 0.35), float3(0.85, 0.68, 0.30),
    float3(0.35, 0.55, 0.90), float3(0.70, 0.45, 0.85), float3(0.35, 0.75, 0.80), float3(0.82, 0.84, 0.86),
    float3(0.35, 0.37, 0.42), float3(1.00, 0.42, 0.42), float3(0.60, 0.95, 0.50), float3(1.00, 0.85, 0.45),
    float3(0.50, 0.70, 1.00), float3(0.85, 0.60, 1.00), float3(0.50, 0.92, 0.95), float3(1.00, 1.00, 1.00)
};

static const uint _Cols = 20, _Rows = 8, _RowOffset = 3;
static const float4 _Cursor = float4(4, 2, 1, 0);
static const float _Margin = 0.015;

// stands in for _Grid.Load(): character, foreground and background numbers as 8-bit values
float3 grid(uint2 cell)
{
    uint ch = 32 + (cell.x * 7 + cell.y * 13) % 95;
    return float3(ch, (cell.x + cell.y) & 15, (cell.x * 3 + cell.y * 5) & 15) / 255.0;
}

// stands in for the glyph atlas
float font(float2 uv, float2 gx, float2 gy)
{
    float2 q = frac(uv * float2(16, 6));
    return saturate(step(0.3, q.x) * step(q.y, 0.7) + length(gx) + length(gy));
}

float4 main(float4 pos : SV_Position) : SV_Target
{
    float2 uv = pos.xy / 128.0;
    float3 c = Palette[0];
    float2 p = (float2(uv.x, 1.0 - uv.y) - _Margin) / (1.0 - 2.0 * _Margin);
    float2 at = p * float2(_Cols, _Rows);
    float2 gx = ddx(at) / float2(16, 6), gy = ddy(at) / float2(16, 6);
    if (p.x >= 0 && p.y >= 0 && p.x < 1 && p.y < 1) {
        uint2 cell = min((uint2)at, uint2(_Cols, _Rows) - 1);
        float2 f = at - cell;
        uint3 t = (uint3)(grid(uint2(cell.x, (cell.y + _RowOffset) % _Rows)) * 255.0 + 0.5);
        uint ch = t.r < 32 || t.r > 126 ? 0 : t.r - 32;
        float3 fg = Palette[t.g & 15], bg = Palette[t.b & 15];
        if (_Cursor.z > 0.5 && cell.x == (uint)_Cursor.x && cell.y == (uint)_Cursor.y && frac(k * 1.5) < 0.5) {
            float3 swap = fg;
            fg = bg;
            bg = swap;
        }
        float2 glyph = (float2(ch % 16, ch / 16) + f) / float2(16, 6);
        float ink = font(float2(glyph.x, 1.0 - glyph.y), gx, float2(gy.x, -gy.y));
        c = lerp(bg, fg, ink);
    }
    return float4(c, 1);
}
