/*
 * File-based d3dcompiler entry points that libvkd3d-utils does not provide,
 * so the vkd3d based d3dcompiler_47.dll is usable as a drop-in replacement.
 */
#include <stdio.h>
#include <stdlib.h>
#define COBJMACROS
#include <windows.h>
#include <d3dcompiler.h>

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

    hr = D3DCompile2(ID3D10Blob_GetBufferPointer(source), ID3D10Blob_GetBufferSize(source), path, defines,
            include, entrypoint, target, flags1, flags2, 0, NULL, 0, code, errors);
    ID3D10Blob_Release(source);
    return hr;
}
