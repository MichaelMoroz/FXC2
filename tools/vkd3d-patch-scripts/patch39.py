import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/preproc.l")
s = open(path).read()
old = '''    for (i = 0; i < ctx.preprocess_info->macro_count; ++i)
    {
        struct vkd3d_string_buffer body;
        char *name;

        vkd3d_string_buffer_init(&body);
        vkd3d_string_buffer_printf(&body, "%s", ctx.preprocess_info->macros[i].value);
'''
assert s.count(old) == 1
s = s.replace(old, '''    /* fxc2: lets a shader tell this compiler from Microsoft's, for what only
     * one of them can compile (or compile well). */
    {
        struct vkd3d_string_buffer body;
        char *name;

        vkd3d_string_buffer_init(&body);
        vkd3d_string_buffer_printf(&body, "1");
        if (!(name = vkd3d_strdup("__FXC2__")) || !preproc_add_macro(&ctx, &loc, name, NULL, 0, &loc, &body))
        {
            vkd3d_free(name);
            vkd3d_string_buffer_cleanup(&body);
            goto fail;
        }
    }

''' + old)
open(path, "w").write(s)
print("patched")
