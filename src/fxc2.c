/*
 * fxc2 - an fxc.exe-compatible command line front end for the vkd3d-shader
 * HLSL compiler. Produces DXBC (SM4/SM5) and D3D9 bytecode (SM1-3) without
 * Microsoft's d3dcompiler.
 *
 * Statically linked against libvkd3d-utils, which implements the
 * d3dcompiler API (D3DCompile2 & co.) on top of vkd3d-shader.
 */
#include <io.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define COBJMACROS
#include <windows.h>
#include <d3dcompiler.h>

#define MAX_LIST 256

static const char *include_dirs[MAX_LIST];
static unsigned int include_dir_count;

/* Remembers which directory each opened include came from, so nested
 * #include "..." resolves relative to the including file like fxc does. */
struct open_file
{
    struct open_file *next;
    void *data;
    char *dir;
};
static struct open_file *open_files;
static char *root_dir;

static char *dir_of(const char *path)
{
    const char *a = strrchr(path, '/'), *b = strrchr(path, '\\');
    const char *sep = a > b ? a : b;
    size_t len = sep ? (size_t)(sep - path) + 1 : 0;
    char *dir = malloc(len + 1);

    memcpy(dir, path, len);
    dir[len] = 0;
    return dir;
}

static void *read_file(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    void *data;
    long len;

    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    data = malloc(len + 1);
    if (fread(data, 1, len, f) != (size_t)len)
    {
        free(data);
        fclose(f);
        return NULL;
    }
    fclose(f);
    ((char *)data)[len] = 0;
    *size = len;
    return data;
}

static void *try_open(const char *dir, const char *name, size_t *size)
{
    size_t dir_len = strlen(dir);
    bool need_sep = dir_len && dir[dir_len - 1] != '/' && dir[dir_len - 1] != '\\';
    char *path = malloc(dir_len + strlen(name) + 2);
    struct open_file *entry;
    void *data;

    sprintf(path, "%s%s%s", dir, need_sep ? "/" : "", name);
    if ((data = read_file(path, size)))
    {
        entry = malloc(sizeof(*entry));
        entry->data = data;
        entry->dir = dir_of(path);
        entry->next = open_files;
        open_files = entry;
    }
    free(path);
    return data;
}

static HRESULT STDMETHODCALLTYPE include_open(ID3DInclude *iface, D3D_INCLUDE_TYPE type,
        const char *name, const void *parent, const void **data, UINT *size)
{
    const char *parent_dir = root_dir;
    struct open_file *entry;
    size_t len = 0;
    unsigned int i;
    void *ret;

    for (entry = open_files; entry; entry = entry->next)
    {
        if (entry->data == parent)
            parent_dir = entry->dir;
    }

    if (!(ret = try_open(parent_dir, name, &len)))
    {
        for (i = 0; i < include_dir_count && !ret; ++i)
            ret = try_open(include_dirs[i], name, &len);
    }
    if (!ret && !(ret = try_open("", name, &len)))
        return E_FAIL;

    *data = ret;
    *size = len;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE include_close(ID3DInclude *iface, const void *data)
{
    struct open_file **entry, *cur;

    for (entry = &open_files; (cur = *entry); entry = &cur->next)
    {
        if (cur->data == data)
        {
            *entry = cur->next;
            free(cur->dir);
            free(cur->data);
            free(cur);
            break;
        }
    }
    return S_OK;
}

static ID3DIncludeVtbl include_vtbl = {include_open, include_close};
static ID3DInclude include_handler = {&include_vtbl};

static void usage(void)
{
    puts("fxc2 - HLSL to DXBC compiler built on vkd3d-shader (no d3dcompiler/fxc needed)\n"
            "\n"
            "Usage: fxc2 <options> <file.hlsl>\n"
            "\n"
            "  /T <profile>    target profile: {vs,ps,gs,hs,ds,cs}_{4_0,4_1,5_0,5_1},\n"
            "                  {vs,ps}_{1_1..3_0}, fx_{2_0,4_0,4_1,5_0}\n"
            "  /E <name>       entry point (default: main)\n"
            "  /Fo <file>      write compiled object (DXBC container)\n"
            "  /Fh <file>      write C header containing the object\n"
            "  /Fc <file>      write assembly listing\n"
            "  /Vn <name>      variable name for /Fh (default: g_<entry>)\n"
            "  /D <id>[=text]  define macro\n"
            "  /I <dir>        additional include directory\n"
            "  /P <file>       preprocess to file instead of compiling\n"
            "  /Zpr /Zpc       pack matrices row-major / column-major\n"
            "  /Od /O0../O3    optimisation level (accepted; vkd3d has one level)\n"
            "  /Zi /Zss /Zsb   accepted and ignored\n"
            "  /Gec            enable backwards compatibility mode\n"
            "  /Ges            strict mode\n"
            "  /WX             treat warnings as errors\n"
            "  /Qstrip_reflect /Qstrip_debug   strip RDEF / debug data\n"
            "  /unroll <n>     implicitly unroll loops of up to <n> iterations, like fxc\n"
            "                  does. Default: only loops marked [unroll], falling back\n"
            "                  to 254 if the shader does not compile otherwise.\n"
            "  /dumpbin        treat the input as a compiled object and disassemble it\n"
            "  /nologo         accepted and ignored\n"
            "\n"
            "Options may start with '/' or '-'; values may be attached (/Tps_5_0).");
}

/* Returns the value of option `name` if argv[*i] is that option, consuming
 * the following argument when the value is not attached. */
static const char *option_value(int argc, char **argv, int *i, const char *name)
{
    const char *arg = argv[*i] + 1;
    size_t len = strlen(name);

    if (strncmp(arg, name, len))
        return NULL;
    if (arg[len])
        return arg + len;
    if (*i + 1 >= argc)
    {
        fprintf(stderr, "fxc2: option /%s requires a value\n", name);
        exit(2);
    }
    return argv[++*i];
}

static bool write_file(const char *path, const void *data, size_t size)
{
    FILE *f = fopen(path, "wb");
    bool ok;

    if (!f)
    {
        fprintf(stderr, "fxc2: cannot open '%s' for writing\n", path);
        return false;
    }
    ok = fwrite(data, 1, size, f) == size;
    fclose(f);
    return ok;
}

static bool write_header(const char *path, const char *var, const unsigned char *data, size_t size)
{
    FILE *f = fopen(path, "w");
    size_t i;

    if (!f)
    {
        fprintf(stderr, "fxc2: cannot open '%s' for writing\n", path);
        return false;
    }
    fprintf(f, "const BYTE %s[] =\n{", var);
    for (i = 0; i < size; ++i)
        fprintf(f, "%s%s%3u", i ? "," : "", i % 6 ? " " : "\n    ", data[i]);
    fprintf(f, "\n};\n");
    fclose(f);
    return true;
}

int main(int argc, char **argv)
{
    const char *profile = NULL, *entry = "main", *out_obj = NULL, *out_header = NULL, *out_asm = NULL;
    const char *var_name = NULL, *input = NULL, *out_pp = NULL, *v;
    ID3DBlob *code = NULL, *errors = NULL, *stripped, *text;
    D3D_SHADER_MACRO macros[MAX_LIST + 1];
    unsigned int macro_count = 0;
    UINT flags = 0, strip = 0;
    bool dumpbin = false;
    char var_buf[256];
    size_t size;
    void *data;
    HRESULT hr;
    int i;

    /* vkd3d logs FIXMEs for harmless things like #line; keep stderr for
     * real diagnostics unless the user asked for debug output. */
    if (!getenv("VKD3D_DEBUG"))
        _putenv("VKD3D_DEBUG=none");
    if (!getenv("VKD3D_SHADER_DEBUG"))
        _putenv("VKD3D_SHADER_DEBUG=none");

    for (i = 1; i < argc; ++i)
    {
        const char *arg = argv[i];

        if ((arg[0] != '/' && arg[0] != '-') || !arg[1] || (arg[0] == '/' && !access(arg, 0)))
        {
            input = arg;
            continue;
        }

        if (!strcmp(arg + 1, "?") || !strcmp(arg + 1, "help") || !strcmp(arg + 1, "-help"))
        {
            usage();
            return 0;
        }
        else if (!strcmp(arg + 1, "nologo") || !strcmp(arg + 1, "Zi") || !strcmp(arg + 1, "Zss")
                || !strcmp(arg + 1, "Zsb") || !strcmp(arg + 1, "Gfa") || !strcmp(arg + 1, "Gfp")
                || !strcmp(arg + 1, "Gpp") || !strcmp(arg + 1, "Op") || !strcmp(arg + 1, "Gis")
                || !strcmp(arg + 1, "Qstrip_priv") || !strcmp(arg + 1, "Qstrip_rootsignature"))
            ;
        else if (!strcmp(arg + 1, "Zpr"))
            flags |= D3DCOMPILE_PACK_MATRIX_ROW_MAJOR;
        else if (!strcmp(arg + 1, "Zpc"))
            flags |= D3DCOMPILE_PACK_MATRIX_COLUMN_MAJOR;
        else if (!strcmp(arg + 1, "Od"))
            flags |= D3DCOMPILE_SKIP_OPTIMIZATION;
        else if (!strcmp(arg + 1, "O0") || !strcmp(arg + 1, "O1") || !strcmp(arg + 1, "O2")
                || !strcmp(arg + 1, "O3"))
            ;
        else if (!strcmp(arg + 1, "Gec"))
            flags |= D3DCOMPILE_ENABLE_BACKWARDS_COMPATIBILITY;
        else if (!strcmp(arg + 1, "Ges"))
            flags |= D3DCOMPILE_ENABLE_STRICTNESS;
        else if (!strcmp(arg + 1, "WX"))
            flags |= D3DCOMPILE_WARNINGS_ARE_ERRORS;
        else if (!strcmp(arg + 1, "Qstrip_reflect"))
            strip |= D3DCOMPILER_STRIP_REFLECTION_DATA;
        else if (!strcmp(arg + 1, "Qstrip_debug"))
            strip |= D3DCOMPILER_STRIP_DEBUG_INFO;
        else if (!strcmp(arg + 1, "dumpbin"))
            dumpbin = true;
        else if ((v = option_value(argc, argv, &i, "unroll")))
        {
            char env[64];

            snprintf(env, sizeof(env), "VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT=%s", v);
            _putenv(env);
        }
        else if ((v = option_value(argc, argv, &i, "Fo")))
            out_obj = v;
        else if ((v = option_value(argc, argv, &i, "Fh")))
            out_header = v;
        else if ((v = option_value(argc, argv, &i, "Fc")))
            out_asm = v;
        else if ((v = option_value(argc, argv, &i, "Fd")))
            ;
        else if ((v = option_value(argc, argv, &i, "Vn")))
            var_name = v;
        else if ((v = option_value(argc, argv, &i, "T")))
            profile = v;
        else if ((v = option_value(argc, argv, &i, "E")))
            entry = v;
        else if ((v = option_value(argc, argv, &i, "P")))
            out_pp = v;
        else if ((v = option_value(argc, argv, &i, "I")))
        {
            if (include_dir_count < MAX_LIST)
                include_dirs[include_dir_count++] = v;
        }
        else if ((v = option_value(argc, argv, &i, "D")))
        {
            char *def = strdup(v), *eq = strchr(def, '=');

            if (eq)
                *eq = 0;
            if (macro_count < MAX_LIST)
            {
                macros[macro_count].Name = def;
                macros[macro_count++].Definition = eq ? eq + 1 : "1";
            }
        }
        else
        {
            fprintf(stderr, "fxc2: unknown option '%s'\n", arg);
            return 2;
        }
    }
    macros[macro_count].Name = macros[macro_count].Definition = NULL;

    if (!input)
    {
        usage();
        return 2;
    }
    if (!(data = read_file(input, &size)))
    {
        fprintf(stderr, "fxc2: cannot read '%s'\n", input);
        return 1;
    }
    root_dir = dir_of(input);

    if (dumpbin)
    {
        if (FAILED(hr = D3DDisassemble(data, size, 0, NULL, &text)))
        {
            fprintf(stderr, "fxc2: disassembly failed, hr %#lx\n", hr);
            return 1;
        }
        if (out_asm)
            return !write_file(out_asm, ID3D10Blob_GetBufferPointer(text), strlen(ID3D10Blob_GetBufferPointer(text)));
        fputs(ID3D10Blob_GetBufferPointer(text), stdout);
        return 0;
    }

    if (out_pp)
    {
        hr = D3DPreprocess(data, size, input, macros, &include_handler, &text, &errors);
        if (errors)
            fputs(ID3D10Blob_GetBufferPointer(errors), stderr);
        if (FAILED(hr))
            return 1;
        return !write_file(out_pp, ID3D10Blob_GetBufferPointer(text), strlen(ID3D10Blob_GetBufferPointer(text)));
    }

    if (!profile)
    {
        fprintf(stderr, "fxc2: no target profile, use /T <profile>\n");
        return 2;
    }

    hr = D3DCompile2(data, size, input, macros, &include_handler, entry, profile, flags, 0, 0, NULL, 0,
            &code, &errors);
    if (FAILED(hr) && !getenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT") && errors
            && (strstr(ID3D10Blob_GetBufferPointer(errors), "E5022")
            || strstr(ID3D10Blob_GetBufferPointer(errors), "Offset must resolve")))
    {
        /* Some shaders are only valid once their loops are unrolled (a loop
         * counter selecting a texture or a texel offset). Retry those the way
         * fxc would have compiled them; other errors would only get slower. */
        ID3DBlob *code2 = NULL, *errors2 = NULL;

        _putenv("VKD3D_HLSL_IMPLICIT_UNROLL_LIMIT=254");
        if (SUCCEEDED(D3DCompile2(data, size, input, macros, &include_handler, entry, profile, flags,
                0, 0, NULL, 0, &code2, &errors2)) && code2)
        {
            hr = S_OK;
            code = code2;
            errors = errors2;
        }
    }
    if (errors)
        fputs(ID3D10Blob_GetBufferPointer(errors), stderr);
    if (FAILED(hr) || !code)
    {
        fprintf(stderr, "fxc2: compilation failed, hr %#lx\n", hr);
        return 1;
    }

    if (strip && SUCCEEDED(D3DStripShader(ID3D10Blob_GetBufferPointer(code),
            ID3D10Blob_GetBufferSize(code), strip, &stripped)))
        code = stripped;

    if (out_obj && !write_file(out_obj, ID3D10Blob_GetBufferPointer(code), ID3D10Blob_GetBufferSize(code)))
        return 1;
    if (out_header)
    {
        if (!var_name)
        {
            snprintf(var_buf, sizeof(var_buf), "g_%s", entry);
            var_name = var_buf;
        }
        if (!write_header(out_header, var_name, ID3D10Blob_GetBufferPointer(code), ID3D10Blob_GetBufferSize(code)))
            return 1;
    }
    if (out_asm || (!out_obj && !out_header))
    {
        if (FAILED(hr = D3DDisassemble(ID3D10Blob_GetBufferPointer(code), ID3D10Blob_GetBufferSize(code),
                0, NULL, &text)))
        {
            fprintf(stderr, "fxc2: disassembly failed, hr %#lx\n", hr);
            return 1;
        }
        if (out_asm)
            return !write_file(out_asm, ID3D10Blob_GetBufferPointer(text), strlen(ID3D10Blob_GetBufferPointer(text)));
        fputs(ID3D10Blob_GetBufferPointer(text), stdout);
    }
    return 0;
}
