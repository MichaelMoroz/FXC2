/*
 * File-based d3dcompiler entry points that libvkd3d-utils does not provide,
 * so the vkd3d based d3dcompiler_47.dll is usable as a drop-in replacement.
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define COBJMACROS
#include <windows.h>
#include <d3dcompiler.h>

/* vkd3d-utils' implementations. The build renames them (objcopy
 * --redefine-sym) so the wrappers below can take over the public names. */
HRESULT WINAPI vkd3d_D3DCompile2(const void *data, SIZE_T data_size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, const char *entrypoint, const char *profile,
        UINT flags, UINT effect_flags, UINT secondary_flags, const void *secondary_data,
        SIZE_T secondary_data_size, ID3DBlob **shader, ID3DBlob **error_messages);
HRESULT WINAPI vkd3d_D3DReflect(const void *data, SIZE_T size, REFIID iid, void **reflection);
HRESULT WINAPI vkd3d_D3DGetBlobPart(const void *data, SIZE_T size, D3D_BLOB_PART part, UINT flags, ID3DBlob **blob);
HRESULT WINAPI vkd3d_D3DStripShader(const void *data, SIZE_T size, UINT flags, ID3DBlob **blob);
HRESULT WINAPI vkd3d_D3DDisassemble(const void *data, SIZE_T size, UINT flags, const char *comments,
        ID3DBlob **blob);
HRESULT WINAPI vkd3d_D3DPreprocess(const void *data, SIZE_T size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, ID3DBlob **shader, ID3DBlob **error_messages);

/* Call tracing, for finding out what a host application asks of the DLL.
 * Enabled by FXC2_LOG=<file>, or, for hosts whose environment is awkward to
 * change, by the existence of %TEMP%\fxc2.log.on (logging to %TEMP%\fxc2.log).
 * Sources that fail to compile are saved next to the log in fxc2_fail\, and
 * ones that take more than two seconds in fxc2_slow\. */
static char log_path[MAX_PATH];
static LONG fail_index;
/* With FXC2_DUMP set, or %TEMP%\fxc2.dump.on present, every source is saved
 * as well, in fxc2_all\, so that a host's whole workload can be replayed. */
static BOOL dump_all;

static void log_init(void)
{
    char temp[MAX_PATH], marker[MAX_PATH];
    const char *env = getenv("FXC2_LOG");

    if (getenv("FXC2_DUMP"))
        dump_all = TRUE;
    if (env && *env)
    {
        snprintf(log_path, sizeof(log_path), "%s", env);
        return;
    }
    if (!GetTempPathA(sizeof(temp), temp))
        return;
    snprintf(marker, sizeof(marker), "%sfxc2.log.on", temp);
    if (GetFileAttributesA(marker) != INVALID_FILE_ATTRIBUTES)
        snprintf(log_path, sizeof(log_path), "%sfxc2.log", temp);
    snprintf(marker, sizeof(marker), "%sfxc2.dump.on", temp);
    if (GetFileAttributesA(marker) != INVALID_FILE_ATTRIBUTES)
        dump_all = TRUE;
}

static void log_line(const char *format, ...)
{
    char line[2048];
    va_list args;
    FILE *f;
    int len;

    if (!log_path[0])
        return;
    len = snprintf(line, sizeof(line), "%lu ", GetCurrentProcessId());
    va_start(args, format);
    vsnprintf(line + len, sizeof(line) - len - 2, format, args);
    va_end(args);
    strcat(line, "\n");
    /* One write per line keeps concurrent processes from interleaving. */
    if ((f = fopen(log_path, "ab")))
    {
        fwrite(line, 1, strlen(line), f);
        fclose(f);
    }
}

static void save_source(const char *kind, const void *data, SIZE_T size, const char *profile, const char *entry,
        UINT flags, ID3DBlob *messages)
{
    char dir[MAX_PATH], path[MAX_PATH + 64], *slash;
    LONG index;
    FILE *f;

    if (!log_path[0])
        return;
    snprintf(dir, sizeof(dir), "%s", log_path);
    if ((slash = strrchr(dir, '\\')) || (slash = strrchr(dir, '/')))
        slash[1] = 0;
    else
        dir[0] = 0;
    strncat(dir, kind, sizeof(dir) - strlen(dir) - 1);
    CreateDirectoryA(dir, NULL);
    index = InterlockedIncrement(&fail_index);
    snprintf(path, sizeof(path), "%s\\%lu_%ld_%s.hlsl", dir, GetCurrentProcessId(), index, profile ? profile : "none");
    if (!(f = fopen(path, "wb")))
        return;
    fprintf(f, "// entry: %s\n", entry ? entry : "(null)");
    fprintf(f, "// flags: %#x\n", flags);
    if (messages)
        fprintf(f, "/*\n%s\n*/\n", (const char *)ID3D10Blob_GetBufferPointer(messages));
    fwrite(data, 1, size, f);
    fclose(f);
    log_line("  source saved to %s", path);
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    /* Silence vkd3d's FIXME logging unless debug output was asked for. */
    if (reason == DLL_PROCESS_ATTACH)
    {
        if (!getenv("VKD3D_DEBUG"))
            _putenv("VKD3D_DEBUG=none");
        if (!getenv("VKD3D_SHADER_DEBUG"))
            _putenv("VKD3D_SHADER_DEBUG=none");
        log_init();
        log_line("attach");
    }
    return TRUE;
}

static HRESULT compile_with_retry(const void *data, SIZE_T data_size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, const char *entrypoint, const char *profile,
        UINT flags, UINT effect_flags, UINT secondary_flags, const void *secondary_data,
        SIZE_T secondary_data_size, ID3DBlob **shader, ID3DBlob **error_messages);

HRESULT WINAPI D3DCompile2(const void *data, SIZE_T data_size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, const char *entrypoint, const char *profile,
        UINT flags, UINT effect_flags, UINT secondary_flags, const void *secondary_data,
        SIZE_T secondary_data_size, ID3DBlob **shader, ID3DBlob **error_messages)
{
    ID3DBlob *messages = NULL;
    DWORD start = GetTickCount(), elapsed;
    HRESULT hr;

    hr = compile_with_retry(data, data_size, filename, macros, include, entrypoint, profile, flags, effect_flags,
            secondary_flags, secondary_data, secondary_data_size, shader, &messages);
    elapsed = GetTickCount() - start;
    log_line("D3DCompile %s %s flags=%#x size=%lu hr=%#lx %lums", profile ? profile : "(null)",
            entrypoint ? entrypoint : "(null)", flags, (unsigned long)data_size, hr, elapsed);
    if (FAILED(hr))
        save_source("fxc2_fail", data, data_size, profile, entrypoint, flags, messages);
    else if (elapsed > 2000)
        save_source("fxc2_slow", data, data_size, profile, entrypoint, flags, messages);
    if (dump_all)
        save_source("fxc2_all", data, data_size, profile, entrypoint, flags, NULL);
    if (error_messages)
        *error_messages = messages;
    else if (messages)
        ID3D10Blob_Release(messages);
    return hr;
}

#define LOGGED(name, call) \
    HRESULT hr = call; \
    if (FAILED(hr)) \
        log_line(name " hr=%#lx", hr); \
    return hr;

HRESULT WINAPI D3DReflect(const void *data, SIZE_T size, REFIID iid, void **reflection)
{
    LOGGED("D3DReflect", vkd3d_D3DReflect(data, size, iid, reflection))
}

HRESULT WINAPI D3DGetBlobPart(const void *data, SIZE_T size, D3D_BLOB_PART part, UINT flags, ID3DBlob **blob)
{
    HRESULT hr = vkd3d_D3DGetBlobPart(data, size, part, flags, blob);

    if (FAILED(hr))
        log_line("D3DGetBlobPart part=%d hr=%#lx", part, hr);
    return hr;
}

HRESULT WINAPI D3DStripShader(const void *data, SIZE_T size, UINT flags, ID3DBlob **blob)
{
    LOGGED("D3DStripShader", vkd3d_D3DStripShader(data, size, flags, blob))
}

HRESULT WINAPI D3DDisassemble(const void *data, SIZE_T size, UINT flags, const char *comments, ID3DBlob **blob)
{
    LOGGED("D3DDisassemble", vkd3d_D3DDisassemble(data, size, flags, comments, blob))
}

HRESULT WINAPI D3DPreprocess(const void *data, SIZE_T size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, ID3DBlob **shader, ID3DBlob **error_messages)
{
    LOGGED("D3DPreprocess", vkd3d_D3DPreprocess(data, size, filename, macros, include, shader, error_messages))
}

/* The compiler is built not to unroll loops speculatively (see patches/).
 * Some shaders are only valid once unrolled, e.g. when a loop counter selects
 * a texture, so on failure compile again the way fxc would have. The limit is
 * passed through the environment, which is process wide: a compile running
 * concurrently on another thread may unroll too, which is slower but correct. */
static HRESULT compile_with_retry(const void *data, SIZE_T data_size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, const char *entrypoint, const char *profile,
        UINT flags, UINT effect_flags, UINT secondary_flags, const void *secondary_data,
        SIZE_T secondary_data_size, ID3DBlob **shader, ID3DBlob **error_messages)
{
    ID3DBlob *retry_shader = NULL, *retry_messages = NULL;
    HRESULT hr;

    hr = vkd3d_D3DCompile2(data, data_size, filename, macros, include, entrypoint, profile, flags, effect_flags,
            secondary_flags, secondary_data, secondary_data_size, shader, error_messages);
    if (SUCCEEDED(hr) || getenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT"))
        return hr;
    /* Unrolling a big shader can take minutes, so only do it for the errors
     * it can cure: a resource or a texel offset that depends on a loop
     * counter and has to be a compile-time constant. */
    if (!error_messages || !*error_messages
            || (!strstr(ID3D10Blob_GetBufferPointer(*error_messages), "E5022")
            && !strstr(ID3D10Blob_GetBufferPointer(*error_messages), "Offset must resolve")))
        return hr;
    log_line("  retrying with loop unrolling");

    _putenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT=254");
    if (SUCCEEDED(vkd3d_D3DCompile2(data, data_size, filename, macros, include, entrypoint, profile, flags,
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

HRESULT WINAPI D3DCompile(const void *data, SIZE_T data_size, const char *filename,
        const D3D_SHADER_MACRO *macros, ID3DInclude *include, const char *entrypoint, const char *profile,
        UINT flags, UINT effect_flags, ID3DBlob **shader, ID3DBlob **error_messages)
{
    return D3DCompile2(data, data_size, filename, macros, include, entrypoint, profile, flags,
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

    hr = D3DCompile2(ID3D10Blob_GetBufferPointer(source), ID3D10Blob_GetBufferSize(source), path, defines,
            include, entrypoint, target, flags1, flags2, 0, NULL, 0, code, errors);
    ID3D10Blob_Release(source);
    return hr;
}
