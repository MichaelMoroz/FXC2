// profile: cs_5_0
// compute: 8
// Executed on WARP: u0 is a 1024 byte raw buffer, u1 a 64 element structured
// buffer of 16 byte elements; the final contents are compared against FXC's.
struct Particle { float3 pos; float life; };

RWByteAddressBuffer raw : register(u0);
RWStructuredBuffer<Particle> particles : register(u1);

groupshared uint shared_sum[8];

uint hash(uint x)
{
    x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
    return x;
}

[numthreads(8, 1, 1)]
void main(uint3 id : SV_DispatchThreadID, uint gi : SV_GroupIndex, uint3 gid : SV_GroupID)
{
    uint idx = id.x;
    uint n = 64, stride = 16;

    shared_sum[gi] = raw.Load(idx * 16) & 0xffu;
    GroupMemoryBarrierWithGroupSync();
    uint total = 0;
    for (uint k = 0; k < 8; ++k)
        total += shared_sum[k];

    Particle p = particles.Load(idx);
    uint3 seed = raw.Load3(idx * 16 + 4);
    float3 vel = float3(hash(seed.x) & 1023u, hash(seed.y) & 1023u, hash(seed.z) & 1023u) / 1024.0 - 0.5;
    for (uint step = 0; step < (idx & 7u) + 1u; ++step)
    {
        p.pos += vel * 0.25;
        p.life -= 0.125;
        if (p.life <= 0.0)
        {
            p.life = (hash(idx ^ step) & 0xffffu) / 65535.0;
            p.pos = 0;
        }
    }
    particles[idx] = p;

    raw.Store(idx * 16, total + gid.x * 1000u);
    raw.Store2(idx * 16 + 4, uint2(hash(idx), n * stride));
    raw.Store(idx * 16 + 12, asuint(p.life));
}
