// profile: cs_5_0
struct Particle { float3 pos; float life; float3 vel; uint id; };

RWStructuredBuffer<Particle> particles : register(u0);
RWTexture2D<float4> outImage : register(u1);
Texture2D<float4> inImage : register(t0);
StructuredBuffer<float4> forces : register(t1);
RWByteAddressBuffer counters : register(u2);

cbuffer Params : register(b0) { float dt; uint count; uint2 dims; };

uint hash(uint x)
{
    x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
    return x;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID, uint gi : SV_GroupIndex)
{
    uint idx = id.y * dims.x + id.x;
    if (idx < count)
    {
        Particle p = particles[idx];
        float3 f = 0;
        for (uint k = 0; k < 4; ++k)
            f += forces[k].xyz * forces[k].w;
        p.vel += f * dt;
        p.pos += p.vel * dt;
        p.life -= dt;
        if (p.life <= 0)
        {
            p.life = (hash(idx ^ p.id) & 0xffff) / 65535.0;
            p.pos = 0;
            uint prev;
            counters.InterlockedAdd(0, 1, prev);
        }
        particles[idx] = p;
    }
    float4 c = inImage[id.xy];
    uint w, h;
    inImage.GetDimensions(w, h);
    c.rgb = pow(abs(c.rgb), 2.2) * (float)(id.x < w / 2);
    outImage[id.xy] = c + inImage.Load(int3(id.xy, 0), int2(1, 0)) * 0.25;
}
