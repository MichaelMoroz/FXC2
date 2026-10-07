/*
 * File-based d3dcompiler entry points that libvkd3d-utils does not provide,
 * so the vkd3d based d3dcompiler_47.dll is usable as a drop-in replacement.
 */
#include <stdio.h>
#include <stdlib.h>
#define COBJMACROS
#include <windows.h>
#include <d3dcompiler.h>

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    /* Silence vkd3d's FIXME logging unless debug output was asked for. */
    if (reason == DLL_PROCESS_ATTACH)
    {
        if (!getenv("VKD3D_DEBUG"))
            _putenv("VKD3D_DEBUG=none");
        if (!getenv("VKD3D_SHADER_DEBUG"))
            _putenv("VKD3D_SHADER_DEBUG=none");
    }
    return TRUE;
}

/* The compiler is built not to unroll loops speculatively (see patches/).
 * Some shaders are only valid once unrolled, e.g. when a loop counter selects
 * a texture, so on failure compile again the way fxc would have. The limit is
 * passed through the environment, which is process wide: a compile running
 * concurrently on another thread may unroll too, which is slower but correct. */
HRESULT WINAPI fxc2_D3DCompile2(const void *data, SIZE_T data_size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, const char *entrypoint, const char *profile,
        UINT flags, UINT effect_flags, UINT secondary_flags, const void *secondary_data,
        SIZE_T secondary_data_size, ID3DBlob **shader, ID3DBlob **error_messages)
{
    ID3DBlob *retry_shader = NULL, *retry_messages = NULL;
    HRESULT hr;

    hr = D3DCompile2(data, data_size, filename, macros, include, entrypoint, profile, flags, effect_flags,
            secondary_flags, secondary_data, secondary_data_size, shader, error_messages);
    if (SUCCEEDED(hr) || getenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT"))
        return hr;

    _putenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT=254");
    if (SUCCEEDED(D3DCompile2(data, data_size, filename, macros, include, entrypoint, profile, flags,
            effect_flags, secondary_flags, secondary_data, secondary_data_size, &retry_shader, &retry_messages)))
    {
        if (error_messages)
        {
            if (*error_messages)
                ID3D10Blob_Release(*error_messages);
            *error_messages = retry_messages;
        }
        else if (retry_messages)
        {
            ID3D10Blob_Release(retry_messages);
        }
        if (shader)
            *shader = retry_shader;
        else if (retry_shader)
            ID3D10Blob_Release(retry_shader);
        hr = S_OK;
    }
    else if (retry_messages)
    {
        ID3D10Blob_Release(retry_messages);
    }
    _putenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT=");
    return hr;
}

HRESULT WINAPI fxc2_D3DCompile(const void *data, SIZE_T data_size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, const char *entrypoint, const char *profile,
        UINT flags, UINT effect_flags, ID3DBlob **shader, ID3DBlob **error_messages)
{
    return fxc2_D3DCompile2(data, data_size, filename, macros, include, entrypoint, profile, flags,
            effect_flags, 0, NULL, 0, shader, error_messages);
}

HRESULT WINAPI D3DReadFileToBlob(const WCHAR *filename, ID3DBlob **contents)
{
    DWORD size, read;
    HANDLE file;
    HRESULT hr;

    file = CreateFileW(filename, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return HRESULT_FROM_WIN32(GetLastError());

    size = GetFileSize(file, NULL);
    if (SUCCEEDED(hr = D3DCreateBlob(size, contents))
            && (!ReadFile(file, ID3D10Blob_GetBufferPointer(*contents), size, &read, NULL) || read != size))
    {
        hr = HRESULT_FROM_WIN32(GetLastError());
        ID3D10Blob_Release(*contents);
        *contents = NULL;
    }
    CloseHandle(file);
    return hr;
}

HRESULT WINAPI D3DWriteBlobToFile(ID3DBlob *blob, const WCHAR *filename, BOOL overwrite)
{
    DWORD written;
    HANDLE file;
    HRESULT hr = S_OK;

    file = CreateFileW(filename, GENERIC_WRITE, 0, NULL, overwrite ? CREATE_ALWAYS : CREATE_NEW, 0, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return HRESULT_FROM_WIN32(GetLastError());
    if (!WriteFile(file, ID3D10Blob_GetBufferPointer(blob), ID3D10Blob_GetBufferSize(blob), &written, NULL))
        hr = HRESULT_FROM_WIN32(GetLastError());
    CloseHandle(file);
    return hr;
}

HRESULT WINAPI D3DCompileFromFile(const WCHAR *filename, const D3D_SHADER_MACRO *defines, ID3DInclude *include,
        const char *entrypoint, const char *target, UINT flags1, UINT flags2, ID3DBlob **code, ID3DBlob **errors)
{
    char path[MAX_PATH * 3];
    ID3DBlob *source;
    HRESULT hr;

    if (FAILED(hr = D3DReadFileToBlob(filename, &source)))
        return hr;
    /* The standard include handler opens includes relative to this name. */
    if (!WideCharToMultiByte(CP_ACP, 0, filename, -1, path, sizeof(path), NULL, NULL))
        path[0] = 0;

    hr = fxc2_D3DCompile2(ID3D10Blob_GetBufferPointer(source), ID3D10Blob_GetBufferSize(source), path, defines,
            include, entrypoint, target, flags1, flags2, 0, NULL, 0, code, errors);
    ID3D10Blob_Release(source);
    return hr;
}
