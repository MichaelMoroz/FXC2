import os
path = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.y")
s = open(path).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old
    s = s.replace(old, new)


rep('''static bool intrinsic_firstbithigh(struct hlsl_ctx *ctx,
        const struct parse_initializer *params, const struct vkd3d_shader_location *loc)
{''', '''/* fxc2: shader model 4 has no bit scan instructions; FXC emulates
 * firstbithigh() and firstbitlow() there, and so does this. "prepare" turns
 * the argument into a value whose highest set bit is the answer. */
static bool intrinsic_sm4_bit_scan(struct hlsl_ctx *ctx, const struct parse_initializer *params,
        const struct vkd3d_shader_location *loc, const char *name, const char *prepare)
{
    struct hlsl_type *arg_type = params->args[0]->data_type, *type;
    struct hlsl_ir_function_decl *func;
    char *body;

    static const char template[] =
            "%s %s(%s x)\\n"
            "{\\n"
            "    %s v = %s, o = v, r = 0, s;\\n"
            "    s = (%s)(v > 0xffffu) * 16u; v >>= s; r += s;\\n"
            "    s = (%s)(v > 0xffu) * 8u; v >>= s; r += s;\\n"
            "    s = (%s)(v > 0xfu) * 4u; v >>= s; r += s;\\n"
            "    s = (%s)(v > 0x3u) * 2u; v >>= s; r += s;\\n"
            "    r += v >> 1;\\n"
            "    return r - (%s)(o == 0u);\\n"
            "}";

    type = hlsl_change_base_type(ctx, arg_type, HLSL_TYPE_UINT);
    if (!(body = hlsl_sprintf_alloc(ctx, template, type->name, name, arg_type->name, type->name, prepare,
            type->name, type->name, type->name, type->name, type->name)))
        return false;
    func = hlsl_compile_internal_function(ctx, name, body);
    vkd3d_free(body);
    if (!func)
        return false;

    return !!add_user_call(ctx, func, params, loc);
}

static bool intrinsic_firstbithigh(struct hlsl_ctx *ctx,
        const struct parse_initializer *params, const struct vkd3d_shader_location *loc)
{''')

rep('''    operands[0] = params->args[0];
    if (hlsl_version_lt(ctx, 5, 0))
        return add_expr(ctx, params->instrs, HLSL_OP1_FIND_MSB, operands, type, loc);
''', '''    operands[0] = params->args[0];
    if (hlsl_version_lt(ctx, 5, 0))
    {
        /* For negative values the first zero bit is the one looked for. */
        if (hlsl_type_is_unsigned_integer(params->args[0]->data_type))
            return intrinsic_sm4_bit_scan(ctx, params, loc, "firstbithigh", "x");
        return intrinsic_sm4_bit_scan(ctx, params, loc, "firstbithigh", "x ^ (x >> 31)");
    }
''')

rep('''    type = hlsl_change_base_type(ctx, params->args[0]->data_type, HLSL_TYPE_UINT);

    operands[0] = params->args[0];
    return add_expr(ctx, params->instrs, HLSL_OP1_CTZ, operands, type, loc);
''', '''    type = hlsl_change_base_type(ctx, params->args[0]->data_type, HLSL_TYPE_UINT);

    /* x & -x isolates the lowest set bit. */
    if (hlsl_version_lt(ctx, 5, 0))
        return intrinsic_sm4_bit_scan(ctx, params, loc, "firstbitlow", "x & (0u - x)");

    operands[0] = params->args[0];
    return add_expr(ctx, params->instrs, HLSL_OP1_CTZ, operands, type, loc);
''')
open(path, "w").write(s)
print("patched")
