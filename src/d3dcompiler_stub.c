/*
 * Forwarding stub for hosts that do not LoadLibrary() d3dcompiler_47.dll but
 * map it with a private PE loader. Unity's UnityShaderCompiler.exe does this:
 * it maps the DLL itself and binds its imports to its own minimal emulation
 * of the Win32 API (the same mechanism lets it run Microsoft's compiler on
 * macOS and Linux), so a DLL loaded that way cannot reach the real system
 * through its import table and nothing bigger than Microsoft's DLL expects
 * works.
 *
 * This stub therefore has no C runtime, no TLS and no imports at all. On
 * first use it finds the real kernel32 through the PEB, loads the actual
 * compiler, fxc2_d3dcompiler.dll, from the host executable's directory with
 * the regular Windows loader, and forwards every call to it.
 */
#include <windows.h>

static const WCHAR real_dll[] = L"fxc2_d3dcompiler.dll";

static HMODULE real_module;
static FARPROC (WINAPI *real_GetProcAddress)(HMODULE, const char *);

static int name_equals(const WCHAR *a, unsigned int len, const char *b)
{
    unsigned int i;

    for (i = 0; i < len; ++i)
    {
        WCHAR c = a[i];

        if (c >= 'A' && c <= 'Z')
            c += 'a' - 'A';
        if (!b[i] || c != (WCHAR)b[i])
            return 0;
    }
    return !b[len];
}

/* Walks the loader's module list in the PEB. */
static BYTE *find_module(const char *name)
{
    BYTE *peb = (BYTE *)__readgsqword(0x60);
    BYTE *ldr = *(BYTE **)(peb + 0x18);
    BYTE *head = ldr + 0x20, *link;     /* InMemoryOrderModuleList */

    for (link = *(BYTE **)head; link != head; link = *(BYTE **)link)
    {
        /* link points at LDR_DATA_TABLE_ENTRY.InMemoryOrderLinks (+0x10). */
        BYTE *base = *(BYTE **)(link + 0x20);
        USHORT length = *(USHORT *)(link + 0x48);
        const WCHAR *buffer = *(const WCHAR **)(link + 0x50);

        if (base && buffer && name_equals(buffer, length / sizeof(WCHAR), name))
            return base;
    }
    return NULL;
}

static int str_equals(const char *a, const char *b)
{
    while (*a && *a == *b)
    {
        ++a;
        ++b;
    }
    return *a == *b;
}

static void *find_export(BYTE *base, const char *name)
{
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_EXPORT_DIRECTORY *dir = (IMAGE_EXPORT_DIRECTORY *)(base
            + nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT].VirtualAddress);
    DWORD *names = (DWORD *)(base + dir->AddressOfNames);
    WORD *ordinals = (WORD *)(base + dir->AddressOfNameOrdinals);
    DWORD *functions = (DWORD *)(base + dir->AddressOfFunctions);
    DWORD i;

    for (i = 0; i < dir->NumberOfNames; ++i)
    {
        if (str_equals((const char *)(base + names[i]), name))
            return base + functions[ordinals[i]];
    }
    return NULL;
}

#ifdef STUB_TRACE
/* Debug aid: appends a line to C:\Users\Public\fxc2_stub_trace.txt using the
 * real kernel32, since the host's emulated one cannot be trusted to. */
static void trace(const char *text, ULONG_PTR value)
{
    HANDLE (WINAPI *create_file)(const char *, DWORD, DWORD, void *, DWORD, DWORD, HANDLE);
    BOOL (WINAPI *write_file)(HANDLE, const void *, DWORD, DWORD *, void *);
    BOOL (WINAPI *close_handle)(HANDLE);
    BYTE *kernel32 = find_module("kernel32.dll");
    char line[256];
    DWORD n = 0, written, i;
    HANDLE file;

    if (!kernel32)
        return;
    create_file = find_export(kernel32, "CreateFileA");
    write_file = find_export(kernel32, "WriteFile");
    close_handle = find_export(kernel32, "CloseHandle");
    while (*text && n < 200)
        line[n++] = *text++;
    line[n++] = ' ';
    for (i = 0; i < 16; ++i)
        line[n++] = "0123456789abcdef"[(value >> (60 - 4 * i)) & 15];
    line[n++] = '\n';
    file = create_file("C:\\Users\\Public\\fxc2_stub_trace.txt", FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
            NULL, OPEN_ALWAYS, 0, NULL);
    if (file != INVALID_HANDLE_VALUE)
    {
        write_file(file, line, n, &written, NULL);
        close_handle(file);
    }
}
#else
#define trace(text, value)
#endif

static HMODULE load_real(void)
{
    DWORD (WINAPI *get_module_file_name)(HMODULE, WCHAR *, DWORD);
    HMODULE (WINAPI *load_library)(const WCHAR *);
    WCHAR path[MAX_PATH + 32];
    DWORD len, i, dir = 0;
    BYTE *kernel32;

    if (real_module)
        return real_module;
    if (!(kernel32 = find_module("kernel32.dll")))
        return NULL;
    get_module_file_name = find_export(kernel32, "GetModuleFileNameW");
    load_library = find_export(kernel32, "LoadLibraryW");
    real_GetProcAddress = find_export(kernel32, "GetProcAddress");
    if (!get_module_file_name || !load_library || !real_GetProcAddress)
        return NULL;

    len = get_module_file_name(NULL, path, MAX_PATH);
    for (i = 0; i < len; ++i)
    {
        if (path[i] == '\\' || path[i] == '/')
            dir = i + 1;
    }
    for (i = 0; i < sizeof(real_dll) / sizeof(WCHAR); ++i)
        path[dir + i] = real_dll[i];

    real_module = load_library(path);
    trace("LoadLibraryW result", (ULONG_PTR)real_module);
    return real_module;
}

static FARPROC resolve(FARPROC *cache, const char *name)
{
    HMODULE module;

    if (!*cache && (module = load_real()))
        *cache = real_GetProcAddress(module, name);
    return *cache;
}

typedef HRESULT (WINAPI *fn4)(void *, void *, void *, void *);
typedef HRESULT (WINAPI *fn5)(void *, void *, void *, void *, void *);
typedef HRESULT (WINAPI *fn7)(void *, void *, void *, void *, void *, void *, void *);
typedef HRESULT (WINAPI *fn8)(void *, void *, void *, void *, void *, void *, void *, void *);
typedef HRESULT (WINAPI *fn9)(void *, void *, void *, void *, void *, void *, void *, void *, void *);
typedef HRESULT (WINAPI *fn11)(void *, void *, void *, void *, void *, void *, void *, void *, void *, void *,
        void *);
typedef HRESULT (WINAPI *fn14)(void *, void *, void *, void *, void *, void *, void *, void *, void *, void *,
        void *, void *, void *, void *);

/* Every parameter of these functions is pointer sized or smaller, so on x64
 * they can be passed through as opaque pointers. */
#define FORWARD(name, type, params, args) \
    HRESULT WINAPI name params \
    { \
        static FARPROC cache; \
        FARPROC f = resolve(&cache, #name); \
        trace(#name, (ULONG_PTR)f); \
        return f ? ((type)f) args : E_NOTIMPL; \
    }

FORWARD(D3DCompile, fn11,
        (void *a, void *b, void *c, void *d, void *e, void *f_, void *g, void *h, void *i, void *j, void *k),
        (a, b, c, d, e, f_, g, h, i, j, k))
FORWARD(D3DCompile2, fn14,
        (void *a, void *b, void *c, void *d, void *e, void *f_, void *g, void *h, void *i, void *j, void *k,
        void *l, void *m, void *n),
        (a, b, c, d, e, f_, g, h, i, j, k, l, m, n))
FORWARD(D3DCompileFromFile, fn9,
        (void *a, void *b, void *c, void *d, void *e, void *f_, void *g, void *h, void *i),
        (a, b, c, d, e, f_, g, h, i))
FORWARD(D3DAssemble, fn8,
        (void *a, void *b, void *c, void *d, void *e, void *f_, void *g, void *h),
        (a, b, c, d, e, f_, g, h))
FORWARD(D3DPreprocess, fn7,
        (void *a, void *b, void *c, void *d, void *e, void *f_, void *g),
        (a, b, c, d, e, f_, g))
FORWARD(D3DDisassemble, fn5, (void *a, void *b, void *c, void *d, void *e), (a, b, c, d, e))
FORWARD(D3DGetBlobPart, fn5, (void *a, void *b, void *c, void *d, void *e), (a, b, c, d, e))
FORWARD(D3DReflect, fn4, (void *a, void *b, void *c, void *d), (a, b, c, d))
FORWARD(D3DStripShader, fn4, (void *a, void *b, void *c, void *d), (a, b, c, d))
FORWARD(D3DGetDebugInfo, fn4, (void *a, void *b, void *c, void *d), (a, b, c, NULL))
FORWARD(D3DGetInputSignatureBlob, fn4, (void *a, void *b, void *c, void *d), (a, b, c, NULL))
FORWARD(D3DGetOutputSignatureBlob, fn4, (void *a, void *b, void *c, void *d), (a, b, c, NULL))
FORWARD(D3DGetInputAndOutputSignatureBlob, fn4, (void *a, void *b, void *c, void *d), (a, b, c, NULL))
FORWARD(D3DCreateBlob, fn4, (void *a, void *b, void *c, void *d), (a, b, NULL, NULL))
FORWARD(D3DReadFileToBlob, fn4, (void *a, void *b, void *c, void *d), (a, b, NULL, NULL))
FORWARD(D3DWriteBlobToFile, fn4, (void *a, void *b, void *c, void *d), (a, b, c, NULL))

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    return TRUE;
}
