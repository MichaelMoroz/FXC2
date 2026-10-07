// shaderbench: runs compiled D3D11 shaders (DXBC) on the GPU with made-up but deterministic
// inputs and times them, so that the same shader built by two compilers can be compared
// without the application it came from. Driven by tools/shaderbench.py, which compiles the
// sources, writes the manifest and reads the result lines; see there for what is measured.
//
//   shaderbench.exe <manifest> <results> [first item]
//
// Manifest, one item a line, tab separated:  name  stage  label blob aux  [label blob aux ...]
// stage is "ps" or "vs"; aux is the vertex shader to draw a pixel shader with ("-" for a
// vertex shader). Result lines (appended, flushed per line so a crash loses nothing):
//
//   I <item> <name>                                  item started
//   R <item> <label> ok <ns per pixel or vertex> <draws timed> <ms for them>
//   R <item> <label> fail <reason>
//   D <item> <label> <label> <max difference> <fraction of pixels that differ>    outputs of two blobs
//   E <item>                                         item finished
//
// Everything a shader reads is created from its reflection data: constant buffers are filled by
// variable name and type (floats 0.25 to 0.75, matrices near identity, integers 1 to 3), every
// texture is a small noise texture, structured and raw buffers are zero. Two builds of one
// shader therefore see the same values, whatever their layout.
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

static ComPtr<ID3D11Device> g_dev;
static ComPtr<ID3D11DeviceContext> g_ctx;
static ComPtr<ID3D11Query> g_disjoint, g_t0, g_t1;
static FILE* g_out;

static const UINT kTarget = 1024;       // pixel shaders: a 1024 x 1024 target (less of it for very slow ones)
static const UINT kVertices = 65536;    // vertex shaders: this many points a draw

static uint32_t hash32(const char* s, uint32_t salt) {
    uint32_t h = 2166136261u ^ (salt * 0x9E3779B1u);
    for (; *s; ++s) { h ^= (uint8_t)*s; h *= 16777619u; }
    h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12; h *= 0x297A2D39u; h ^= h >> 15;
    return h;
}
static float hfloat(const char* s, uint32_t salt) { return (hash32(s, salt) & 0xffff) / 65535.0f; }

static std::vector<uint8_t> readFile(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}

static void emit(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_out, fmt, ap);
    va_end(ap);
    fputc('\n', g_out);
    fflush(g_out);
}

static void checkDevice() {
    HRESULT hr = g_dev->GetDeviceRemovedReason();
    if (FAILED(hr)) {
        fprintf(stderr, "device removed: 0x%08lx\n", (unsigned long)hr);
        fflush(g_out);
        ExitProcess(3);
    }
}

// ---- constant buffers ---------------------------------------------------------------------

static bool isMatrix(D3D_SHADER_VARIABLE_CLASS c) { return c == D3D_SVC_MATRIX_ROWS || c == D3D_SVC_MATRIX_COLUMNS; }

static UINT elementSize(ID3D11ShaderReflectionType* t, const D3D11_SHADER_TYPE_DESC& d);

static UINT typeSize(ID3D11ShaderReflectionType* t) {
    D3D11_SHADER_TYPE_DESC d;
    if (FAILED(t->GetDesc(&d))) return 0;
    UINT e = elementSize(t, d), n = d.Elements ? d.Elements : 1;
    return n > 1 ? (n - 1) * ((e + 15) & ~15u) + e : e;
}

static UINT elementSize(ID3D11ShaderReflectionType* t, const D3D11_SHADER_TYPE_DESC& d) {
    if (d.Class == D3D_SVC_STRUCT) {
        UINT size = 0;
        for (UINT m = 0; m < d.Members; ++m) {
            ID3D11ShaderReflectionType* mt = t->GetMemberTypeByIndex(m);
            D3D11_SHADER_TYPE_DESC md;
            if (FAILED(mt->GetDesc(&md))) continue;
            size = std::max(size, md.Offset + typeSize(mt));
        }
        return size;
    }
    if (isMatrix(d.Class)) {
        bool colMajor = d.Class == D3D_SVC_MATRIX_COLUMNS;
        UINT regs = colMajor ? d.Columns : d.Rows, comps = colMajor ? d.Rows : d.Columns;
        return (regs - 1) * 16 + comps * 4;
    }
    return d.Columns * 4;
}

static void fillType(ID3D11ShaderReflectionType* t, std::vector<uint8_t>& data, size_t offset, const std::string& name) {
    D3D11_SHADER_TYPE_DESC d;
    if (FAILED(t->GetDesc(&d))) return;
    UINT elements = d.Elements ? d.Elements : 1;
    UINT stride = (elementSize(t, d) + 15) & ~15u;
    for (UINT e = 0; e < elements; ++e) {
        size_t base = offset + (size_t)e * stride;
        if (d.Class == D3D_SVC_STRUCT) {
            for (UINT m = 0; m < d.Members; ++m) {
                ID3D11ShaderReflectionType* mt = t->GetMemberTypeByIndex(m);
                D3D11_SHADER_TYPE_DESC md;
                if (FAILED(mt->GetDesc(&md))) continue;
                const char* mn = t->GetMemberTypeName(m);
                fillType(mt, data, base + md.Offset, name + "." + (mn ? mn : "?"));
            }
            continue;
        }
        if (d.Class != D3D_SVC_SCALAR && d.Class != D3D_SVC_VECTOR && !isMatrix(d.Class)) continue;
        bool matrix = isMatrix(d.Class), colMajor = d.Class == D3D_SVC_MATRIX_COLUMNS;
        for (UINT r = 0; r < d.Rows; ++r) {
            for (UINT c = 0; c < d.Columns; ++c) {
                size_t o = base + (matrix ? (colMajor ? c * 16 + r * 4 : r * 16 + c * 4) : c * 4);
                if (o + 4 > data.size()) continue;
                float h = hfloat(name.c_str(), e * 16 + r * 4 + c);
                if (d.Type == D3D_SVT_FLOAT) {
                    float v = matrix ? (r == c ? 1.0f : 0.0f) + 0.02f * (h - 0.5f) : 0.25f + 0.5f * h;
                    memcpy(&data[o], &v, 4);
                } else if (d.Type == D3D_SVT_INT || d.Type == D3D_SVT_UINT) {
                    uint32_t v = 1 + hash32(name.c_str(), e * 16 + r * 4 + c) % 3;
                    memcpy(&data[o], &v, 4);
                } else if (d.Type == D3D_SVT_BOOL) {
                    uint32_t v = 1;
                    memcpy(&data[o], &v, 4);
                }
            }
        }
    }
}

// ---- resources ----------------------------------------------------------------------------

struct Bindings {
    std::vector<ComPtr<IUnknown>> keep;
};

static void setCB(char stage, UINT slot, ID3D11Buffer* b) {
    if (stage == 'p') g_ctx->PSSetConstantBuffers(slot, 1, &b); else g_ctx->VSSetConstantBuffers(slot, 1, &b);
}
static void setSRV(char stage, UINT slot, ID3D11ShaderResourceView* v) {
    if (stage == 'p') g_ctx->PSSetShaderResources(slot, 1, &v); else g_ctx->VSSetShaderResources(slot, 1, &v);
}
static void setSampler(char stage, UINT slot, ID3D11SamplerState* s) {
    if (stage == 'p') g_ctx->PSSetSamplers(slot, 1, &s); else g_ctx->VSSetSamplers(slot, 1, &s);
}

static DXGI_FORMAT texelFormat(D3D_RESOURCE_RETURN_TYPE rt) {
    if (rt == D3D_RETURN_TYPE_UINT) return DXGI_FORMAT_R8G8B8A8_UINT;
    if (rt == D3D_RETURN_TYPE_SINT) return DXGI_FORMAT_R8G8B8A8_SINT;
    return DXGI_FORMAT_R8G8B8A8_UNORM;
}

static std::vector<uint8_t> noise(size_t texels, bool integer) {
    std::vector<uint8_t> d(texels * 4);
    for (size_t i = 0; i < d.size(); ++i) {
        uint32_t h = hash32("texel", (uint32_t)i);
        d[i] = integer ? (uint8_t)(h & 3) : (uint8_t)(h >> 8);
    }
    return d;
}

static bool makeTexture(const D3D11_SHADER_INPUT_BIND_DESC& b, ComPtr<ID3D11ShaderResourceView>& srv, Bindings& keep, std::string& err) {
    bool integer = b.ReturnType == D3D_RETURN_TYPE_UINT || b.ReturnType == D3D_RETURN_TYPE_SINT;
    DXGI_FORMAT format = texelFormat(b.ReturnType);
    HRESULT hr = E_FAIL;
    switch (b.Dimension) {
        case D3D_SRV_DIMENSION_BUFFER: {
            DXGI_FORMAT f = b.ReturnType == D3D_RETURN_TYPE_UINT ? DXGI_FORMAT_R32G32B32A32_UINT
                    : b.ReturnType == D3D_RETURN_TYPE_SINT ? DXGI_FORMAT_R32G32B32A32_SINT : DXGI_FORMAT_R32G32B32A32_FLOAT;
            std::vector<uint32_t> data(4096 * 4);
            for (size_t i = 0; i < data.size(); ++i) {
                float v = hfloat("buffer", (uint32_t)i);
                if (integer) data[i] = hash32("buffer", (uint32_t)i) & 3; else memcpy(&data[i], &v, 4);
            }
            D3D11_BUFFER_DESC bd = {(UINT)data.size() * 4, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0, 0, 0};
            D3D11_SUBRESOURCE_DATA init = {data.data(), 0, 0};
            ComPtr<ID3D11Buffer> buf;
            if (FAILED(hr = g_dev->CreateBuffer(&bd, &init, &buf))) break;
            D3D11_SHADER_RESOURCE_VIEW_DESC vd = {};
            vd.Format = f; vd.ViewDimension = D3D11_SRV_DIMENSION_BUFFER; vd.Buffer.NumElements = 4096;
            hr = g_dev->CreateShaderResourceView(buf.Get(), &vd, &srv);
            keep.keep.push_back(buf);
            break;
        }
        case D3D_SRV_DIMENSION_TEXTURE1D:
        case D3D_SRV_DIMENSION_TEXTURE1DARRAY: {
            bool array = b.Dimension == D3D_SRV_DIMENSION_TEXTURE1DARRAY;
            std::vector<uint8_t> data = noise(64, integer);
            D3D11_TEXTURE1D_DESC td = {64, 1, array ? 4u : 1u, format, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0, 0};
            std::vector<D3D11_SUBRESOURCE_DATA> init(td.ArraySize, D3D11_SUBRESOURCE_DATA{data.data(), 0, 0});
            ComPtr<ID3D11Texture1D> tex;
            if (FAILED(hr = g_dev->CreateTexture1D(&td, init.data(), &tex))) break;
            D3D11_SHADER_RESOURCE_VIEW_DESC vd = {};
            vd.Format = format;
            if (array) { vd.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE1DARRAY; vd.Texture1DArray.MipLevels = 1; vd.Texture1DArray.ArraySize = 4; }
            else { vd.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE1D; vd.Texture1D.MipLevels = 1; }
            hr = g_dev->CreateShaderResourceView(tex.Get(), &vd, &srv);
            keep.keep.push_back(tex);
            break;
        }
        case D3D_SRV_DIMENSION_TEXTURE2D:
        case D3D_SRV_DIMENSION_TEXTURE2DARRAY:
        case D3D_SRV_DIMENSION_TEXTURECUBE:
        case D3D_SRV_DIMENSION_TEXTURECUBEARRAY: {
            bool cube = b.Dimension == D3D_SRV_DIMENSION_TEXTURECUBE || b.Dimension == D3D_SRV_DIMENSION_TEXTURECUBEARRAY;
            UINT layers = b.Dimension == D3D_SRV_DIMENSION_TEXTURE2D ? 1 : b.Dimension == D3D_SRV_DIMENSION_TEXTURE2DARRAY ? 4
                    : b.Dimension == D3D_SRV_DIMENSION_TEXTURECUBE ? 6 : 12;
            std::vector<uint8_t> data = noise(64 * 64, integer);
            D3D11_TEXTURE2D_DESC td = {64, 64, 1, layers, format, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0,
                    cube ? (UINT)D3D11_RESOURCE_MISC_TEXTURECUBE : 0u};
            std::vector<D3D11_SUBRESOURCE_DATA> init(layers, D3D11_SUBRESOURCE_DATA{data.data(), 64 * 4, 0});
            ComPtr<ID3D11Texture2D> tex;
            if (FAILED(hr = g_dev->CreateTexture2D(&td, init.data(), &tex))) break;
            D3D11_SHADER_RESOURCE_VIEW_DESC vd = {};
            vd.Format = format;
            switch (b.Dimension) {
                case D3D_SRV_DIMENSION_TEXTURE2D: vd.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D; vd.Texture2D.MipLevels = 1; break;
                case D3D_SRV_DIMENSION_TEXTURE2DARRAY: vd.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2DARRAY;
                    vd.Texture2DArray.MipLevels = 1; vd.Texture2DArray.ArraySize = 4; break;
                case D3D_SRV_DIMENSION_TEXTURECUBE: vd.ViewDimension = D3D11_SRV_DIMENSION_TEXTURECUBE; vd.TextureCube.MipLevels = 1; break;
                default: vd.ViewDimension = D3D11_SRV_DIMENSION_TEXTURECUBEARRAY; vd.TextureCubeArray.MipLevels = 1;
                    vd.TextureCubeArray.NumCubes = 2; break;
            }
            hr = g_dev->CreateShaderResourceView(tex.Get(), &vd, &srv);
            keep.keep.push_back(tex);
            break;
        }
        case D3D_SRV_DIMENSION_TEXTURE3D: {
            std::vector<uint8_t> data = noise(32 * 32 * 32, integer);
            D3D11_TEXTURE3D_DESC td = {32, 32, 32, 1, format, D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0, 0};
            D3D11_SUBRESOURCE_DATA init = {data.data(), 32 * 4, 32 * 32 * 4};
            ComPtr<ID3D11Texture3D> tex;
            if (FAILED(hr = g_dev->CreateTexture3D(&td, &init, &tex))) break;
            hr = g_dev->CreateShaderResourceView(tex.Get(), nullptr, &srv);
            keep.keep.push_back(tex);
            break;
        }
        default:
            err = "texture dimension " + std::to_string((int)b.Dimension);
            return false;
    }
    if (FAILED(hr)) { err = "texture " + std::string(b.Name); return false; }
    return true;
}

static bool bindResources(ID3D11ShaderReflection* refl, char stage, Bindings& keep, std::string& err) {
    D3D11_SHADER_DESC sd;
    refl->GetDesc(&sd);
    for (UINT i = 0; i < sd.BoundResources; ++i) {
        D3D11_SHADER_INPUT_BIND_DESC b;
        if (FAILED(refl->GetResourceBindingDesc(i, &b))) continue;
        UINT count = b.BindCount ? b.BindCount : 1;
        switch (b.Type) {
            case D3D_SIT_CBUFFER: {
                ID3D11ShaderReflectionConstantBuffer* cb = refl->GetConstantBufferByName(b.Name);
                D3D11_SHADER_BUFFER_DESC cd;
                if (!cb || FAILED(cb->GetDesc(&cd))) { err = "cbuffer " + std::string(b.Name); return false; }
                std::vector<uint8_t> data((cd.Size + 15) & ~15u, 0);
                for (UINT v = 0; v < cd.Variables; ++v) {
                    ID3D11ShaderReflectionVariable* var = cb->GetVariableByIndex(v);
                    D3D11_SHADER_VARIABLE_DESC vd;
                    if (FAILED(var->GetDesc(&vd))) continue;
                    fillType(var->GetType(), data, vd.StartOffset, vd.Name);
                }
                D3D11_BUFFER_DESC bd = {(UINT)data.size(), D3D11_USAGE_DEFAULT, D3D11_BIND_CONSTANT_BUFFER, 0, 0, 0};
                D3D11_SUBRESOURCE_DATA init = {data.data(), 0, 0};
                ComPtr<ID3D11Buffer> buf;
                if (data.empty() || FAILED(g_dev->CreateBuffer(&bd, &init, &buf))) { err = "cbuffer " + std::string(b.Name); return false; }
                setCB(stage, b.BindPoint, buf.Get());
                keep.keep.push_back(buf);
                break;
            }
            case D3D_SIT_TEXTURE: {
                ComPtr<ID3D11ShaderResourceView> srv;
                if (!makeTexture(b, srv, keep, err)) return false;
                for (UINT k = 0; k < count; ++k) setSRV(stage, b.BindPoint + k, srv.Get());
                keep.keep.push_back(srv);
                break;
            }
            case D3D_SIT_SAMPLER: {
                D3D11_SAMPLER_DESC d = {};
                bool cmp = (b.uFlags & D3D_SIF_COMPARISON_SAMPLER) != 0;
                d.Filter = cmp ? D3D11_FILTER_COMPARISON_MIN_MAG_LINEAR_MIP_POINT : D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT;
                d.AddressU = d.AddressV = d.AddressW = D3D11_TEXTURE_ADDRESS_WRAP;
                d.ComparisonFunc = cmp ? D3D11_COMPARISON_LESS_EQUAL : D3D11_COMPARISON_NEVER;
                d.MaxAnisotropy = 1;
                d.MaxLOD = D3D11_FLOAT32_MAX;
                ComPtr<ID3D11SamplerState> s;
                if (FAILED(g_dev->CreateSamplerState(&d, &s))) { err = "sampler"; return false; }
                for (UINT k = 0; k < count; ++k) setSampler(stage, b.BindPoint + k, s.Get());
                keep.keep.push_back(s);
                break;
            }
            case D3D_SIT_STRUCTURED:
            case D3D_SIT_BYTEADDRESS: {
                bool raw = b.Type == D3D_SIT_BYTEADDRESS;
                UINT stride = raw ? 4 : (b.NumSamples && b.NumSamples != ~0u ? b.NumSamples : 4);
                std::vector<uint8_t> data((size_t)stride * 1024, 0);
                D3D11_BUFFER_DESC bd = {(UINT)data.size(), D3D11_USAGE_DEFAULT, D3D11_BIND_SHADER_RESOURCE, 0,
                        raw ? (UINT)D3D11_RESOURCE_MISC_BUFFER_ALLOW_RAW_VIEWS : (UINT)D3D11_RESOURCE_MISC_BUFFER_STRUCTURED, raw ? 0 : stride};
                D3D11_SUBRESOURCE_DATA init = {data.data(), 0, 0};
                ComPtr<ID3D11Buffer> buf;
                if (FAILED(g_dev->CreateBuffer(&bd, &init, &buf))) { err = "buffer " + std::string(b.Name); return false; }
                D3D11_SHADER_RESOURCE_VIEW_DESC vd = {};
                vd.ViewDimension = D3D11_SRV_DIMENSION_BUFFEREX;
                vd.Format = raw ? DXGI_FORMAT_R32_TYPELESS : DXGI_FORMAT_UNKNOWN;
                vd.BufferEx.NumElements = raw ? (UINT)data.size() / 4 : 1024;
                vd.BufferEx.Flags = raw ? D3D11_BUFFEREX_SRV_FLAG_RAW : 0;
                ComPtr<ID3D11ShaderResourceView> srv;
                if (FAILED(g_dev->CreateShaderResourceView(buf.Get(), &vd, &srv))) { err = "buffer view " + std::string(b.Name); return false; }
                setSRV(stage, b.BindPoint, srv.Get());
                keep.keep.push_back(buf);
                keep.keep.push_back(srv);
                break;
            }
            case D3D_SIT_TBUFFER:
                err = "tbuffer";
                return false;
            default:
                err = "unordered access view";
                return false;
        }
    }
    return true;
}

// ---- timing -------------------------------------------------------------------------------

template <typename T> static bool getData(ID3D11Query* q, T& value) {
    for (int i = 0; i < 20000; ++i) {
        HRESULT hr = g_ctx->GetData(q, &value, sizeof(value), 0);
        if (hr == S_OK) return true;
        if (FAILED(hr)) { checkDevice(); return false; }
        Sleep(i < 2000 ? 0 : 1);
    }
    return false;
}

// Milliseconds of GPU time for "draws" calls of draw(); negative if it could not be measured.
template <typename F> static double timeDraws(F draw, UINT draws) {
    for (int attempt = 0; attempt < 4; ++attempt) {
        g_ctx->Begin(g_disjoint.Get());
        g_ctx->End(g_t0.Get());
        for (UINT i = 0; i < draws; ++i) draw();
        g_ctx->End(g_t1.Get());
        g_ctx->End(g_disjoint.Get());
        g_ctx->Flush();
        UINT64 a = 0, b = 0;
        D3D11_QUERY_DATA_TIMESTAMP_DISJOINT dj = {};
        if (!getData(g_t0.Get(), a) || !getData(g_t1.Get(), b) || !getData(g_disjoint.Get(), dj)) { checkDevice(); return -1; }
        if (!dj.Disjoint && dj.Frequency) return (double)(b - a) * 1000.0 / (double)dj.Frequency;
    }
    return -1;
}

// Finds a number of draws that takes about 25 ms, then reports the fastest of five such runs.
template <typename F> static bool measure(F draw, double units, double& nsPerUnit, UINT& drawsOut, double& msOut, std::string& err) {
    UINT draws = 1;
    double ms = timeDraws(draw, draws);    // also warms up: the driver compiles the shader here
    ms = timeDraws(draw, draws);
    if (ms < 0) { err = "timer"; return false; }
    while (ms < 20.0 && draws < (1u << 16)) {
        double scale = ms > 0.01 ? 25.0 / ms : 16.0;
        draws = (UINT)std::min<double>(1u << 16, std::max<double>(draws * 2.0, draws * std::min(scale, 16.0)));
        ms = timeDraws(draw, draws);
        if (ms < 0) { err = "timer"; return false; }
    }
    double best = ms;
    for (int i = 0; i < 5; ++i) {
        ms = timeDraws(draw, draws);
        if (ms > 0) best = std::min(best, ms);
    }
    nsPerUnit = best * 1e6 / (draws * units);
    drawsOut = draws;
    msOut = best;
    return true;
}

// ---- running one blob ---------------------------------------------------------------------

struct Signature { std::vector<D3D11_SIGNATURE_PARAMETER_DESC> in, out; };

static DXGI_FORMAT targetFormat(D3D_REGISTER_COMPONENT_TYPE t) {
    return t == D3D_REGISTER_COMPONENT_UINT32 ? DXGI_FORMAT_R32G32B32A32_UINT
            : t == D3D_REGISTER_COMPONENT_SINT32 ? DXGI_FORMAT_R32G32B32A32_SINT : DXGI_FORMAT_R32G32B32A32_FLOAT;
}

static ComPtr<ID3DBlob> compileBuiltin(const char* source, const char* profile) {
    ComPtr<ID3DBlob> code, errors;
    D3DCompile(source, strlen(source), "builtin", nullptr, nullptr, "main", profile, 0, 0, &code, &errors);
    return code;
}

struct Output { std::vector<uint8_t> data; DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN; };

static bool runPixel(const std::vector<uint8_t>& blob, const std::string& vsPath, double& ns, UINT& draws, double& ms,
        Output& output, std::string& err) {
    ComPtr<ID3D11ShaderReflection> refl;
    if (FAILED(D3DReflect(blob.data(), blob.size(), IID_PPV_ARGS(&refl)))) { err = "reflect"; return false; }
    ComPtr<ID3D11PixelShader> ps;
    if (FAILED(g_dev->CreatePixelShader(blob.data(), blob.size(), nullptr, &ps))) { err = "CreatePixelShader"; return false; }
    std::vector<uint8_t> vsBlob = readFile(vsPath);
    ComPtr<ID3D11VertexShader> vs;
    if (vsBlob.empty() || FAILED(g_dev->CreateVertexShader(vsBlob.data(), vsBlob.size(), nullptr, &vs))) { err = "companion vertex shader"; return false; }

    D3D11_SHADER_DESC sd;
    refl->GetDesc(&sd);
    DXGI_FORMAT formats[8] = {};
    UINT targets = 0;
    for (UINT i = 0; i < sd.OutputParameters; ++i) {
        D3D11_SIGNATURE_PARAMETER_DESC p;
        if (FAILED(refl->GetOutputParameterDesc(i, &p))) continue;
        if (p.SystemValueType == D3D_NAME_TARGET && p.SemanticIndex < 8) {
            formats[p.SemanticIndex] = targetFormat(p.ComponentType);
            targets = std::max(targets, p.SemanticIndex + 1);
        }
    }
    if (!targets) { targets = 1; }
    Bindings keep;
    std::vector<ID3D11RenderTargetView*> rtvs;
    ComPtr<ID3D11Texture2D> first;
    for (UINT i = 0; i < targets; ++i) {
        if (formats[i] == DXGI_FORMAT_UNKNOWN) formats[i] = DXGI_FORMAT_R32G32B32A32_FLOAT;
        D3D11_TEXTURE2D_DESC td = {kTarget, kTarget, 1, 1, formats[i], {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_RENDER_TARGET, 0, 0};
        ComPtr<ID3D11Texture2D> tex;
        ComPtr<ID3D11RenderTargetView> rtv;
        if (FAILED(g_dev->CreateTexture2D(&td, nullptr, &tex)) || FAILED(g_dev->CreateRenderTargetView(tex.Get(), nullptr, &rtv))) { err = "render target"; return false; }
        if (!i) first = tex;
        rtvs.push_back(rtv.Get());
        keep.keep.push_back(tex);
        keep.keep.push_back(rtv);
    }
    if (!bindResources(refl.Get(), 'p', keep, err)) return false;

    g_ctx->OMSetRenderTargets((UINT)rtvs.size(), rtvs.data(), nullptr);
    g_ctx->IASetInputLayout(nullptr);
    g_ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    g_ctx->VSSetShader(vs.Get(), nullptr, 0);
    g_ctx->PSSetShader(ps.Get(), nullptr, 0);
    auto draw = [] { g_ctx->Draw(3, 0); };

    // A few pixels first: a shader that loops forever on made-up inputs must not hang the GPU.
    D3D11_VIEWPORT tiny = {0, 0, 4, 4, 0, 1};
    g_ctx->RSSetViewports(1, &tiny);
    double probe = timeDraws(draw, 1);
    probe = timeDraws(draw, 1);
    if (probe < 0) { err = "timer"; return false; }
    if (probe > 20.0) { err = "too slow on these inputs (" + std::to_string(probe / 16.0) + " ms a pixel)"; return false; }

    // Then 64 x 64 for an estimate, and as much of the target as keeps one draw under 0.3 s.
    D3D11_VIEWPORT medium = {0, 0, 64, 64, 0, 1};
    g_ctx->RSSetViewports(1, &medium);
    probe = timeDraws(draw, 1);
    if (probe < 0) { err = "timer"; return false; }
    UINT side = kTarget;
    while (side > 64 && probe / 4096.0 * side * side > 300.0) side /= 2;
    D3D11_VIEWPORT full = {0, 0, (float)side, (float)side, 0, 1};
    g_ctx->RSSetViewports(1, &full);
    if (!measure(draw, (double)side * side, ns, draws, ms, err)) return false;

    // what it computed, for comparing the builds
    float zero[4] = {0, 0, 0, 0};
    g_ctx->ClearRenderTargetView(rtvs[0], zero);
    g_ctx->Draw(3, 0);
    D3D11_TEXTURE2D_DESC sdsc = {kTarget, kTarget, 1, 1, formats[0], {1, 0}, D3D11_USAGE_STAGING, 0, D3D11_CPU_ACCESS_READ, 0};
    ComPtr<ID3D11Texture2D> staging;
    if (SUCCEEDED(g_dev->CreateTexture2D(&sdsc, nullptr, &staging))) {
        g_ctx->CopyResource(staging.Get(), first.Get());
        D3D11_MAPPED_SUBRESOURCE m;
        if (SUCCEEDED(g_ctx->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &m))) {
            output.format = formats[0];
            output.data.resize((size_t)kTarget * kTarget * 16);
            for (UINT y = 0; y < kTarget; ++y)
                memcpy(&output.data[(size_t)y * kTarget * 16], (const uint8_t*)m.pData + (size_t)y * m.RowPitch, kTarget * 16);
            g_ctx->Unmap(staging.Get(), 0);
        }
    }
    return true;
}

static bool runVertex(const std::vector<uint8_t>& blob, ID3D11PixelShader* whitePs, double& ns, UINT& draws, double& ms, std::string& err) {
    ComPtr<ID3D11ShaderReflection> refl;
    if (FAILED(D3DReflect(blob.data(), blob.size(), IID_PPV_ARGS(&refl)))) { err = "reflect"; return false; }
    ComPtr<ID3D11VertexShader> vs;
    if (FAILED(g_dev->CreateVertexShader(blob.data(), blob.size(), nullptr, &vs))) { err = "CreateVertexShader"; return false; }
    D3D11_SHADER_DESC sd;
    refl->GetDesc(&sd);

    bool position = false;
    for (UINT i = 0; i < sd.OutputParameters; ++i) {
        D3D11_SIGNATURE_PARAMETER_DESC p;
        if (SUCCEEDED(refl->GetOutputParameterDesc(i, &p)) && p.SystemValueType == D3D_NAME_POSITION) position = true;
    }
    if (!position) { err = "no SV_Position output (feeds a geometry or tessellation stage)"; return false; }

    std::vector<D3D11_INPUT_ELEMENT_DESC> layout;
    std::vector<std::string> names(sd.InputParameters);
    std::vector<D3D11_SIGNATURE_PARAMETER_DESC> inputs;
    UINT stride = 0;
    for (UINT i = 0; i < sd.InputParameters; ++i) {
        D3D11_SIGNATURE_PARAMETER_DESC p;
        if (FAILED(refl->GetInputParameterDesc(i, &p))) continue;
        if (p.SystemValueType != D3D_NAME_UNDEFINED) continue;   // vertex and instance ids come from the pipeline
        UINT comps = p.Mask & 8 ? 4 : p.Mask & 4 ? 3 : p.Mask & 2 ? 2 : 1;
        static const DXGI_FORMAT f[3][4] = {
            {DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R32G32_FLOAT, DXGI_FORMAT_R32G32B32_FLOAT, DXGI_FORMAT_R32G32B32A32_FLOAT},
            {DXGI_FORMAT_R32_UINT, DXGI_FORMAT_R32G32_UINT, DXGI_FORMAT_R32G32B32_UINT, DXGI_FORMAT_R32G32B32A32_UINT},
            {DXGI_FORMAT_R32_SINT, DXGI_FORMAT_R32G32_SINT, DXGI_FORMAT_R32G32B32_SINT, DXGI_FORMAT_R32G32B32A32_SINT}};
        int kind = p.ComponentType == D3D_REGISTER_COMPONENT_UINT32 ? 1 : p.ComponentType == D3D_REGISTER_COMPONENT_SINT32 ? 2 : 0;
        names[i] = p.SemanticName;
        layout.push_back({names[i].c_str(), p.SemanticIndex, f[kind][comps - 1], 0, stride, D3D11_INPUT_PER_VERTEX_DATA, 0});
        inputs.push_back(p);
        stride += comps * 4;
    }
    Bindings keep;
    ComPtr<ID3D11InputLayout> il;
    if (!layout.empty()) {
        if (FAILED(g_dev->CreateInputLayout(layout.data(), (UINT)layout.size(), blob.data(), blob.size(), &il))) { err = "input layout"; return false; }
        std::vector<uint8_t> data((size_t)stride * kVertices);
        for (UINT v = 0; v < kVertices; ++v) {
            for (size_t e = 0; e < layout.size(); ++e) {
                UINT comps = inputs[e].Mask & 8 ? 4 : inputs[e].Mask & 4 ? 3 : inputs[e].Mask & 2 ? 2 : 1;
                bool integer = inputs[e].ComponentType != D3D_REGISTER_COMPONENT_FLOAT32;
                for (UINT c = 0; c < comps; ++c) {
                    uint32_t salt = v * 64 + (uint32_t)e * 4 + c;
                    size_t o = (size_t)v * stride + layout[e].AlignedByteOffset + c * 4;
                    if (integer) { uint32_t x = hash32("vertex", salt) & 3; memcpy(&data[o], &x, 4); }
                    else { float x = hfloat("vertex", salt) * 2.0f - 1.0f; memcpy(&data[o], &x, 4); }
                }
            }
        }
        D3D11_BUFFER_DESC bd = {(UINT)data.size(), D3D11_USAGE_DEFAULT, D3D11_BIND_VERTEX_BUFFER, 0, 0, 0};
        D3D11_SUBRESOURCE_DATA init = {data.data(), 0, 0};
        ComPtr<ID3D11Buffer> vb;
        if (FAILED(g_dev->CreateBuffer(&bd, &init, &vb))) { err = "vertex buffer"; return false; }
        UINT offset = 0;
        ID3D11Buffer* b = vb.Get();
        g_ctx->IASetVertexBuffers(0, 1, &b, &stride, &offset);
        keep.keep.push_back(vb);
    }
    if (!bindResources(refl.Get(), 'v', keep, err)) return false;

    D3D11_TEXTURE2D_DESC td = {4, 4, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM, {1, 0}, D3D11_USAGE_DEFAULT, D3D11_BIND_RENDER_TARGET, 0, 0};
    ComPtr<ID3D11Texture2D> tex;
    ComPtr<ID3D11RenderTargetView> rtv;
    if (FAILED(g_dev->CreateTexture2D(&td, nullptr, &tex)) || FAILED(g_dev->CreateRenderTargetView(tex.Get(), nullptr, &rtv))) { err = "render target"; return false; }
    ID3D11RenderTargetView* r = rtv.Get();
    g_ctx->OMSetRenderTargets(1, &r, nullptr);
    D3D11_VIEWPORT vp = {0, 0, 4, 4, 0, 1};
    g_ctx->RSSetViewports(1, &vp);
    g_ctx->IASetInputLayout(il.Get());
    g_ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_POINTLIST);
    g_ctx->VSSetShader(vs.Get(), nullptr, 0);
    g_ctx->PSSetShader(whitePs, nullptr, 0);

    auto probeDraw = [] { g_ctx->Draw(64, 0); };
    double probe = timeDraws(probeDraw, 1);
    probe = timeDraws(probeDraw, 1);
    if (probe < 0) { err = "timer"; return false; }
    if (probe > 50.0) { err = "too slow on these inputs"; return false; }
    auto draw = [] { g_ctx->Draw(kVertices, 0); };
    return measure(draw, (double)kVertices, ns, draws, ms, err);
}

static void compare(const Output& a, const Output& b, double& maxDiff, double& fraction) {
    maxDiff = 0;
    size_t differing = 0, pixels = a.data.size() / 16;
    bool isFloat = a.format == DXGI_FORMAT_R32G32B32A32_FLOAT;
    for (size_t p = 0; p < pixels; ++p) {
        bool differs = false;
        for (int c = 0; c < 4; ++c) {
            if (isFloat) {
                float x, y;
                memcpy(&x, &a.data[p * 16 + c * 4], 4);
                memcpy(&y, &b.data[p * 16 + c * 4], 4);
                if (std::isnan(x) && std::isnan(y)) continue;
                if (x == y) continue;
                double d = std::isfinite(x) && std::isfinite(y) ? std::fabs((double)x - y) : 1e30;
                maxDiff = std::max(maxDiff, d);
                if (d > 1e-3 * (1.0 + std::fabs(x))) differs = true;
            } else {
                uint32_t x, y;
                memcpy(&x, &a.data[p * 16 + c * 4], 4);
                memcpy(&y, &b.data[p * 16 + c * 4], 4);
                if (x != y) { differs = true; maxDiff = std::max(maxDiff, (double)(x > y ? x - y : y - x)); }
            }
        }
        differing += differs;
    }
    fraction = pixels ? (double)differing / pixels : 0;
}

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: shaderbench <manifest> <results> [first item]\n"); return 2; }
    int first = argc > 3 ? atoi(argv[3]) : 0;
    g_out = fopen(argv[2], "a");
    if (!g_out) { fprintf(stderr, "cannot open %s\n", argv[2]); return 2; }

    D3D_FEATURE_LEVEL level = D3D_FEATURE_LEVEL_11_0, got;
    if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, &level, 1, D3D11_SDK_VERSION, &g_dev, &got, &g_ctx))) {
        fprintf(stderr, "no D3D11 device\n");
        return 2;
    }
    D3D11_QUERY_DESC qd = {D3D11_QUERY_TIMESTAMP_DISJOINT, 0};
    g_dev->CreateQuery(&qd, &g_disjoint);
    qd.Query = D3D11_QUERY_TIMESTAMP;
    g_dev->CreateQuery(&qd, &g_t0);
    g_dev->CreateQuery(&qd, &g_t1);
    ComPtr<ID3DBlob> whiteBlob = compileBuiltin("float4 main() : SV_Target { return 1; }", "ps_4_0");
    ComPtr<ID3D11PixelShader> whitePs;
    if (whiteBlob) g_dev->CreatePixelShader(whiteBlob->GetBufferPointer(), whiteBlob->GetBufferSize(), nullptr, &whitePs);
    ComPtr<ID3D11RasterizerState> raster;
    D3D11_RASTERIZER_DESC rd = {D3D11_FILL_SOLID, D3D11_CULL_NONE, FALSE, 0, 0, 0, TRUE, FALSE, FALSE, FALSE};
    g_dev->CreateRasterizerState(&rd, &raster);

    std::ifstream manifest(argv[1]);
    std::string line;
    for (int item = 0; std::getline(manifest, line); ++item) {
        if (item < first || line.empty()) continue;
        std::vector<std::string> f;
        std::stringstream ss(line);
        for (std::string field; std::getline(ss, field, '\t');) f.push_back(field);
        if (f.size() < 5) continue;
        emit("I %d %s", item, f[0].c_str());
        std::vector<Output> outputs;
        std::vector<std::string> outputLabels;
        for (size_t k = 2; k + 2 < f.size(); k += 3) {
            const std::string& label = f[k];
            std::vector<uint8_t> blob = readFile(f[k + 1]);
            double ns = 0, ms = 0;
            UINT draws = 0;
            std::string err;
            Output output;
            bool ok = false;
            g_ctx->ClearState();
            g_ctx->RSSetState(raster.Get());
            if (blob.empty()) err = "no bytecode";
            else if (f[1] == "ps") ok = runPixel(blob, f[k + 2], ns, draws, ms, output, err);
            else if (f[1] == "vs") ok = runVertex(blob, whitePs.Get(), ns, draws, ms, err);
            else err = "stage not supported";
            g_ctx->ClearState();
            g_ctx->Flush();
            checkDevice();
            if (ok) emit("R %d %s ok %.4f %u %.3f", item, label.c_str(), ns, draws, ms);
            else emit("R %d %s fail %s", item, label.c_str(), err.c_str());
            if (ok && !output.data.empty() && getenv("SHADERBENCH_DUMP")) {
                // raw RGBA32 of the first target (1024 x 1024), for looking at a difference
                std::string path = std::string(getenv("SHADERBENCH_DUMP")) + "\\" + std::to_string(item) + "_" + label + ".bin";
                if (FILE* dump = fopen(path.c_str(), "wb")) { fwrite(output.data.data(), 1, output.data.size(), dump); fclose(dump); }
            }
            if (ok && !output.data.empty()) {
                for (size_t o = 0; o < outputs.size(); ++o) {
                    if (outputs[o].format != output.format) continue;
                    double maxDiff, fraction;
                    compare(outputs[o], output, maxDiff, fraction);
                    emit("D %d %s %s %.6g %.6f", item, outputLabels[o].c_str(), label.c_str(), maxDiff, fraction);
                }
                outputs.push_back(output);
                outputLabels.push_back(label);
            }
        }
        emit("E %d", item);
    }
    fclose(g_out);
    return 0;
}
