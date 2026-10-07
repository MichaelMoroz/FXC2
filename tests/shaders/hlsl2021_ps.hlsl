// profile: ps_5_0
// via: dxc
// render: 128 128 0.5 0
// HLSL 2021 (templates, operator overloading, enum class): beyond FXC and vkd3d's
// parser, so DXC has to be the front end.
cbuffer C : register(b0) { float2 resolution; float k; float pad; };

template<typename T> T sq(T x) { return x * x; }
template<typename T, int N> T sum(T v[N]) { T s = 0; for (int i = 0; i < N; ++i) s += v[i]; return s; }

enum class Mode : uint { Add, Mul };

struct Complex
{
    float re, im;
    Complex operator*(Complex o) { Complex r; r.re = re * o.re - im * o.im; r.im = re * o.im + im * o.re; return r; }
    Complex operator+(Complex o) { Complex r; r.re = re + o.re; r.im = im + o.im; return r; }
};

float4 main(float4 fc : SV_Position) : SV_Target
{
    float2 uv = (fc.xy * 2.0 - resolution) / resolution.y;
    Complex c; c.re = uv.x - k; c.im = uv.y;
    Complex z = c;
    int n = 0;
    for (; n < 32; ++n)
    {
        z = z * z + c;
        if (sq(z.re) + sq(z.im) > 4.0) break;
    }
    float w[3] = { 0.2, 0.3, 0.5 };
    Mode m = n > 16 ? Mode::Mul : Mode::Add;
    float v = m == Mode::Mul ? sum(w) * n / 32.0 : sq(float2(uv)).x;
    return float4(v, n / 32.0, select(uv.x > 0, 1.0, 0.25), 1);
}
