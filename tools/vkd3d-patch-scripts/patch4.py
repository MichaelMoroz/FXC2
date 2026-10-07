import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old, s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("tpf.c", [
    # register table
    ('''        {"sv_depth",                true,  VKD3D_SHADER_TYPE_PIXEL,    VSIR_REGISTER_DEPTHOUT},
''',
     '''        {"sv_depth",                true,  VKD3D_SHADER_TYPE_PIXEL,    VSIR_REGISTER_DEPTHOUT},
        {"sv_depthgreaterequal",    true,  VKD3D_SHADER_TYPE_PIXEL,    VSIR_REGISTER_DEPTHOUTGE},
        {"sv_depthlessequal",       true,  VKD3D_SHADER_TYPE_PIXEL,    VSIR_REGISTER_DEPTHOUTLE},
'''),
    # sysval table
    ('''        {"sv_depth",                    true,  VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_DEPTH},
''',
     '''        {"sv_depth",                    true,  VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_DEPTH},
        {"sv_depthgreaterequal",        true,  VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_DEPTH_GREATER_EQUAL},
        {"sv_depthlessequal",           true,  VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_DEPTH_LESS_EQUAL},
'''),
    # SV_InstanceID / SV_VertexID are only system values as vertex shader
    # inputs; anywhere else they are ordinary varyings that happen to have
    # that name, which is how instancing code hands the ID down the pipeline.
    ('''        {"sv_clipdistance",             true,  VKD3D_SHADER_TYPE_DOMAIN,    VKD3D_SHADER_SV_CLIP_DISTANCE},
''',
     '''        {"sv_instanceid",               false, VKD3D_SHADER_TYPE_DOMAIN,    VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 false, VKD3D_SHADER_TYPE_DOMAIN,    VKD3D_SHADER_SV_NONE},
        {"sv_instanceid",               true,  VKD3D_SHADER_TYPE_DOMAIN,    VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 true,  VKD3D_SHADER_TYPE_DOMAIN,    VKD3D_SHADER_SV_NONE},
        {"sv_clipdistance",             true,  VKD3D_SHADER_TYPE_DOMAIN,    VKD3D_SHADER_SV_CLIP_DISTANCE},
'''),
    ('''        {"sv_gsinstanceid",             false, VKD3D_SHADER_TYPE_GEOMETRY,  ~0u},
''',
     '''        {"sv_gsinstanceid",             false, VKD3D_SHADER_TYPE_GEOMETRY,  ~0u},
        {"sv_instanceid",               false, VKD3D_SHADER_TYPE_GEOMETRY,  VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 false, VKD3D_SHADER_TYPE_GEOMETRY,  VKD3D_SHADER_SV_NONE},
        {"sv_instanceid",               true,  VKD3D_SHADER_TYPE_GEOMETRY,  VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 true,  VKD3D_SHADER_TYPE_GEOMETRY,  VKD3D_SHADER_SV_NONE},
'''),
    ('''        {"sv_outputcontrolpointid",     false, VKD3D_SHADER_TYPE_HULL,      ~0u},
''',
     '''        {"sv_outputcontrolpointid",     false, VKD3D_SHADER_TYPE_HULL,      ~0u},
        {"sv_instanceid",               false, VKD3D_SHADER_TYPE_HULL,      VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 false, VKD3D_SHADER_TYPE_HULL,      VKD3D_SHADER_SV_NONE},
        {"sv_instanceid",               true,  VKD3D_SHADER_TYPE_HULL,      VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 true,  VKD3D_SHADER_TYPE_HULL,      VKD3D_SHADER_SV_NONE},
'''),
    ('''        {"sv_isfrontface",              false, VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_IS_FRONT_FACE},
''',
     '''        {"sv_instanceid",               false, VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 false, VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_NONE},
        {"sv_isfrontface",              false, VKD3D_SHADER_TYPE_PIXEL,     VKD3D_SHADER_SV_IS_FRONT_FACE},
'''),
    ('''        {"sv_clipdistance",             true,  VKD3D_SHADER_TYPE_VERTEX,    VKD3D_SHADER_SV_CLIP_DISTANCE},
''',
     '''        {"sv_instanceid",               true,  VKD3D_SHADER_TYPE_VERTEX,    VKD3D_SHADER_SV_NONE},
        {"sv_vertexid",                 true,  VKD3D_SHADER_TYPE_VERTEX,    VKD3D_SHADER_SV_NONE},
        {"sv_clipdistance",             true,  VKD3D_SHADER_TYPE_VERTEX,    VKD3D_SHADER_SV_CLIP_DISTANCE},
'''),
    # geometry shader instancing
    ('''static void tpf_write_dcl_vertices_out(struct tpf_compiler *tpf, unsigned int count)
''',
     '''static void tpf_write_dcl_gs_instances(struct tpf_compiler *tpf, unsigned int count)
{
    struct sm4_instruction instr =
    {
        .opcode = VKD3D_SM5_OP_DCL_GS_INSTANCES,

        .idx = {count},
        .idx_count = 1,
    };

    write_sm4_instruction(tpf, &instr);
}

static void tpf_write_dcl_vertices_out(struct tpf_compiler *tpf, unsigned int count)
'''),
    ('''        tpf_write_dcl_vertices_out(tpf, program->vertices_out_count);
    }
''',
     '''        tpf_write_dcl_vertices_out(tpf, program->vertices_out_count);
        if (program->gs_instance_count)
            tpf_write_dcl_gs_instances(tpf, program->gs_instance_count);
    }
'''),
])

edit("vkd3d_shader_private.h", [
    ('''    unsigned int vertices_out_count;
''',
     '''    unsigned int vertices_out_count;
    unsigned int gs_instance_count;
'''),
])

edit("hlsl.h", [
    ('''    unsigned int max_vertex_count;
''',
     '''    unsigned int max_vertex_count;
    unsigned int gs_instance_count;
'''),
])

edit("hlsl_codegen.c", [
    ('''            hlsl_fixme(ctx, &entry_func->attrs[i]->loc, "Geometry shader instance count");
''',
     '''        {
            int value;

            if (attr->args_count != 1)
                hlsl_error(ctx, &attr->loc, VKD3D_SHADER_ERROR_HLSL_WRONG_PARAMETER_COUNT,
                        "Expected 1 parameter for [instance] attribute, but got %u.", attr->args_count);
            else if (get_integral_argument_value(ctx, attr, 0, &value))
                ctx->gs_instance_count = value;
        }
'''),
    ('''        program->vertices_out_count = ctx->max_vertex_count;
''',
     '''        program->vertices_out_count = ctx->max_vertex_count;
        program->gs_instance_count = ctx->gs_instance_count;
'''),
    ('''    if (type == VSIR_REGISTER_DEPTHOUT)
    {
        vsir_operand_init(&dst->reg, type, VSIR_DATA_F32, 0);
''',
     '''    if (type == VSIR_REGISTER_DEPTHOUT || type == VSIR_REGISTER_DEPTHOUTGE || type == VSIR_REGISTER_DEPTHOUTLE)
    {
        vsir_operand_init(&dst->reg, type, VSIR_DATA_F32, 0);
'''),
])

edit("hlsl.y", [
    # A helper that calls this may be compiled into every stage of a shader
    # and only ever be reached from the pixel shader; FXC accepts that.
    ('''    if (ctx->profile->type != VKD3D_SHADER_TYPE_PIXEL || hlsl_version_lt(ctx, 4, 1))
        hlsl_error(ctx, loc, VKD3D_SHADER_ERROR_HLSL_INCOMPATIBLE_PROFILE,
                "GetRenderTargetSampleCount() can only be used from a pixel shader using version 4.1 or higher.");
''',
     '''    if (ctx->profile->type != VKD3D_SHADER_TYPE_PIXEL || hlsl_version_lt(ctx, 4, 1))
        hlsl_warning(ctx, loc, VKD3D_SHADER_WARNING_HLSL_UNKNOWN_ATTRIBUTE,
                "GetRenderTargetSampleCount() is only valid in a pixel shader using version 4.1 or higher.");
'''),
])
print("patched")
