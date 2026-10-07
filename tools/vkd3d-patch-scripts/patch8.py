import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old, s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("preproc.h", [
    ('''    bool last_was_defined;
''', '''    bool last_was_defined;
    /* fxc2: a ## was just seen; its right-hand side is next. */
    bool concat_pending;
'''),
])

edit("preproc.l", [
    ('''                if (token == T_CONCAT && should_concat(ctx))
                {
                    while (ctx->buffer.content_size
                            && strchr(" \\t\\r\\n", ctx->buffer.buffer[ctx->buffer.content_size - 1]))
                        --ctx->buffer.content_size;
                    break;
                }
''', '''                if (token == T_CONCAT && should_concat(ctx))
                {
                    while (ctx->buffer.content_size
                            && strchr(" \\t\\r\\n", ctx->buffer.buffer[ctx->buffer.content_size - 1]))
                        --ctx->buffer.content_size;
                    ctx->concat_pending = !ctx->current_directive;
                    break;
                }

                /* fxc2: the token produced by ## has to be looked up as a
                 * macro itself (#define GET(x) (v >> SHIFT_##x)). Output is
                 * written as it goes, so the left-hand side is already in the
                 * buffer: take it back out when the pasted name is a macro. */
                if (ctx->concat_pending && !ctx->current_directive)
                {
                    if (isspace(text[0]))
                        continue;

                    if (!((token == T_IDENTIFIER || token == T_IDENTIFIER_PAREN) && find_arg_expansion(ctx, text)))
                    {
                        size_t start = ctx->buffer.content_size, left_len, i;
                        struct preproc_macro *macro = NULL;
                        bool pastable = true;
                        char name[256];

                        ctx->concat_pending = false;

                        for (i = 0; text[i]; ++i)
                        {
                            if (!isalnum((unsigned char)text[i]) && text[i] != '_')
                                pastable = false;
                        }
                        while (start && (isalnum((unsigned char)ctx->buffer.buffer[start - 1])
                                || ctx->buffer.buffer[start - 1] == '_'))
                            --start;
                        left_len = ctx->buffer.content_size - start;

                        if (pastable && left_len && !isdigit((unsigned char)ctx->buffer.buffer[start])
                                && left_len + strlen(text) < sizeof(name))
                        {
                            memcpy(name, &ctx->buffer.buffer[start], left_len);
                            strcpy(name + left_len, text);
                            macro = preproc_find_macro(ctx, name);
                        }

                        if (macro)
                        {
                            ctx->buffer.content_size = start;
                            ctx->buffer.buffer[start] = 0;
                            if (!macro->arg_count)
                            {
                                preproc_push_expansion(ctx, &macro->body, macro, NULL);
                            }
                            else
                            {
                                func_state->state = STATE_IDENTIFIER;
                                func_state->macro = macro;
                            }
                            continue;
                        }
                    }
                }
'''),
])
print("patched")
