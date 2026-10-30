// profile: cs_5_0
// compute: 8
// [numthreads] of constant expressions (vkd3d patch 66), as in Unity's AutoExposure.compute: (2, 8 / 4, 1 + 1)
// is 8 threads a group, with a macro, a division and a static const, whatever order they come in.
RWByteAddressBuffer raw : register(u0);
RWStructuredBuffer<float4> particles : register(u1);

#define BINS 8
#define ACROSS BINS / 4
static const int DEEP = 1;

[numthreads(int(2), ACROSS, DEEP + 1)]
void main(uint3 id : SV_DispatchThreadID, uint gi : SV_GroupIndex)
{
    raw.Store(gi * 16, gi + 1 + id.y * 256 + id.z * 65536);
    particles[gi] = float4(gi, id);
}
