import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new, *count in pairs:
        n = count[0] if count else 1
        assert s.count(old) == n, (name, old, s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("hlsl_codegen.c", [
    # --- a scalar double occupies two components of a register -----------
    ('''    if (type->class <= HLSL_CLASS_VECTOR)
        return allocate_register(ctx, allocator, type->e.numeric.dimx, type->e.numeric.dimx, 0, false, false, false);
''', '''    if (type->class <= HLSL_CLASS_VECTOR)
    {
        unsigned int count = type->e.numeric.dimx;

        /* fxc2: a double takes two components. */
        if (type->e.numeric.type == HLSL_TYPE_DOUBLE && hlsl_version_ge(ctx, 4, 0))
            count = min(count * 2, 4);
        return allocate_register(ctx, allocator, count, count, 0, false, false, false);
    }
'''),

    # --- helpers ---------------------------------------------------------
    ('''/* Translate ops that have 1 src and need one instruction for each component in
 * the d3dbc backend. */''', '''/* fxc2: double precision for shader model 5, scalars only.
 *
 * A scalar double lives in two components of a register (.xy or .zw). Source
 * operands name the pair twice (r1.xyxy), and scalar sources of conversions
 * are replicated (r1.xxxx), so that the operand reads the same value whichever
 * half of the destination the instruction is writing. FXC emits the same. */
static bool sm4_type_is_double(const struct hlsl_type *type)
{
    return type->class <= HLSL_CLASS_VECTOR && type->e.numeric.type == HLSL_TYPE_DOUBLE;
}

static void sm4_vsir_src_for_double_op(struct vsir_src_operand *src, struct hlsl_ctx *ctx,
        const struct hlsl_ir_node *instr)
{
    unsigned int c[2], count = 0, i;

    if (instr->type == HLSL_IR_CONSTANT)
    {
        const struct hlsl_ir_constant *constant = hlsl_ir_constant(instr);

        if (!sm4_type_is_double(instr->data_type))
        {
            vsir_src_from_hlsl_node(src, ctx, instr, VKD3DSP_WRITEMASK_0);
            return;
        }
        vsir_src_operand_init(src, VSIR_REGISTER_IMMCONST64, VSIR_DATA_F64, 0);
        src->reg.dimension = VSIR_DIMENSION_VEC4;
        src->swizzle = VKD3D_SHADER_NO_SWIZZLE;
        src->reg.u.immconst_f64[0] = constant->value.u[0].d;
        src->reg.u.immconst_f64[1] = constant->value.u[0].d;
        return;
    }

    vsir_operand_init(&src->reg, instr->reg.type, vsir_data_type_from_hlsl_instruction(ctx, instr), 1);
    src->reg.idx[0].offset = instr->reg.id;
    src->reg.dimension = VSIR_DIMENSION_VEC4;

    for (i = 0; i < 4 && count < 2; ++i)
    {
        if (instr->reg.writemask & (1u << i))
            c[count++] = i;
    }
    if (count == 1)
        c[1] = c[0];
    src->swizzle = vkd3d_shader_create_swizzle(c[0], c[1], c[0], c[1]);
}

static bool sm4_generate_vsir_double_op(struct hlsl_ctx *ctx, struct vsir_program *program,
        struct hlsl_ir_expr *expr, enum vsir_opcode opcode, uint32_t src_mod, bool extension)
{
    struct hlsl_ir_node *instr = &expr->node;
    unsigned int i, src_count = 0;
    struct vsir_instruction *ins;

    for (i = 0; i < HLSL_MAX_OPERANDS; ++i)
    {
        if (!expr->operands[i].node)
            break;
        src_count = i + 1;
        if (expr->operands[i].node->data_type->e.numeric.dimx != 1)
        {
            hlsl_fixme(ctx, &instr->loc, "SM5 double vectors.");
            return false;
        }
    }
    if (hlsl_version_lt(ctx, 5, 0))
    {
        hlsl_error(ctx, &instr->loc, VKD3D_SHADER_ERROR_HLSL_INCOMPATIBLE_PROFILE,
                "The 'double' type requires shader model 5.0 or higher.");
        return false;
    }

    if (!(ins = generate_vsir_add_program_instruction(ctx, program, &instr->loc, opcode, 1, src_count)))
        return false;
    vsir_dst_from_hlsl_node(&ins->dst[0], ctx, instr);
    for (i = 0; i < src_count; ++i)
    {
        sm4_vsir_src_for_double_op(&ins->src[i], ctx, expr->operands[i].node);
        ins->src[i].modifiers = src_mod;
    }

    program->global_flags |= VKD3DSGF_ENABLE_DOUBLE_PRECISION_FLOAT_OPS;
    if (extension)
        program->global_flags |= VKD3DSGF_ENABLE_11_1_DOUBLE_EXTENSIONS;
    return true;
}

/* Translate ops that have 1 src and need one instruction for each component in
 * the d3dbc backend. */'''),

    # --- casts -----------------------------------------------------------
    ('''                case HLSL_TYPE_DOUBLE:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 cast from double to float.");
                    return false;
''', '''                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DTOF, 0, false);
'''),
    ('''                case HLSL_TYPE_DOUBLE:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 cast from double to int.");
                    return false;
''', '''                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DTOI, 0, true);
'''),
    ('''                case HLSL_TYPE_DOUBLE:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 cast from double to uint.");
                    return false;
''', '''                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DTOU, 0, true);
'''),
    ('''        case HLSL_TYPE_DOUBLE:
            hlsl_fixme(ctx, &expr->node.loc, "SM4 cast to double.");
            return false;
''', '''        case HLSL_TYPE_DOUBLE:
            switch (src_type->e.numeric.type)
            {
                case HLSL_TYPE_HALF:
                case HLSL_TYPE_FLOAT:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_FTOD, 0, false);

                case HLSL_TYPE_INT:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_ITOD, 0, true);

                case HLSL_TYPE_MIN16UINT:
                case HLSL_TYPE_UINT:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_UTOD, 0, true);

                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DMOV, 0, false);

                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 cast from bool to double.");
                    return false;
            }
'''),

    # --- arithmetic ------------------------------------------------------
    ('''                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s addition expression.", dst_type_name);
                    return false;
''', '''                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DADD, 0, false);

                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s addition expression.", dst_type_name);
                    return false;
'''),
    ('''                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s division expression.", dst_type_name);
                    return false;
''', '''                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DDIV, 0, true);

                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s division expression.", dst_type_name);
                    return false;
'''),
    ('''                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s multiplication expression.", dst_type_name);
                    return false;
''', '''                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DMUL, 0, false);

                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s multiplication expression.", dst_type_name);
                    return false;
'''),
    ('''                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s negation expression.", dst_type_name);
                    return false;
''', '''                case HLSL_TYPE_DOUBLE:
                    return sm4_generate_vsir_double_op(ctx, program, expr, VSIR_OP_DMOV, VKD3DSPSM_NEG, false);

                default:
                    hlsl_fixme(ctx, &expr->node.loc, "SM4 %s negation expression.", dst_type_name);
                    return false;
'''),
])

edit("tpf.c", [
    ('''            put_u32(buffer, src->reg.u.immconst_u32[3]);
        }
    }
}
''', '''            put_u32(buffer, src->reg.u.immconst_u32[3]);
        }
    }
    else if (src->reg.type == VSIR_REGISTER_IMMCONST64)
    {
        /* fxc2: two doubles, low word first. */
        put_u32(buffer, (uint32_t)src->reg.u.immconst_u64[0]);
        put_u32(buffer, (uint32_t)(src->reg.u.immconst_u64[0] >> 32));
        put_u32(buffer, (uint32_t)src->reg.u.immconst_u64[1]);
        put_u32(buffer, (uint32_t)(src->reg.u.immconst_u64[1] >> 32));
    }
}
'''),
    ('''    if (tpf->program->global_flags & VKD3DSGF_ENABLE_STENCIL_REF)
        *flags |= DXBC_SFI0_REQUIRES_STENCIL_REF;
''', '''    if (tpf->program->global_flags & VKD3DSGF_ENABLE_STENCIL_REF)
        *flags |= DXBC_SFI0_REQUIRES_STENCIL_REF;
    if (tpf->program->global_flags & VKD3DSGF_ENABLE_DOUBLE_PRECISION_FLOAT_OPS)
        *flags |= DXBC_SFI0_REQUIRES_DOUBLES;
    if (tpf->program->global_flags & VKD3DSGF_ENABLE_11_1_DOUBLE_EXTENSIONS)
        *flags |= DXBC_SFI0_REQUIRES_11_1_DOUBLE_EXTENSIONS;
'''),
])
print("patched")

edit("hlsl_codegen.c", [
    ('''    /* These are the only current ops that are not per-component. */
    if (expr->op == HLSL_OP1_COS_REDUCED || expr->op == HLSL_OP1_SIN_REDUCED
            || expr->op == HLSL_OP2_DOT || expr->op == HLSL_OP3_DP2ADD)
        return;
''', '''    /* These are the only current ops that are not per-component. */
    if (expr->op == HLSL_OP1_COS_REDUCED || expr->op == HLSL_OP1_SIN_REDUCED
            || expr->op == HLSL_OP2_DOT || expr->op == HLSL_OP3_DP2ADD)
        return;

    /* fxc2: doubles are only generated as scalars. */
    if (expr->node.data_type->e.numeric.type == HLSL_TYPE_DOUBLE)
        return;
    for (size_t i = 0; i < HLSL_MAX_OPERANDS; ++i)
    {
        if (expr->operands[i].node && expr->operands[i].node->data_type->class <= HLSL_CLASS_VECTOR
                && expr->operands[i].node->data_type->e.numeric.type == HLSL_TYPE_DOUBLE)
            return;
    }
'''),
])
print("patched vectoriser")

edit("ir.c", [
    ('''        case VSIR_OP_IMUL:
        case VSIR_OP_SWAPC:
        case VSIR_OP_UDIV:
        case VSIR_OP_UMUL:
            /* These instructions don't have fixed destinations, but they have
''', '''        case VSIR_OP_DADD:
        case VSIR_OP_DDIV:
        case VSIR_OP_DFMA:
        case VSIR_OP_DMAX:
        case VSIR_OP_DMIN:
        case VSIR_OP_DMOV:
        case VSIR_OP_DMOVC:
        case VSIR_OP_DMUL:
        case VSIR_OP_DRCP:
        case VSIR_OP_DTOF:
        case VSIR_OP_DTOI:
        case VSIR_OP_DTOU:
        case VSIR_OP_FTOD:
        case VSIR_OP_ITOD:
        case VSIR_OP_UTOD:
            /* fxc2: a double has to stay in the .xy or .zw pair it was
             * generated for, and the operands of conversions are laid out
             * for the destination they were generated with. */
        case VSIR_OP_IMUL:
        case VSIR_OP_SWAPC:
        case VSIR_OP_UDIV:
        case VSIR_OP_UMUL:
            /* These instructions don't have fixed destinations, but they have
'''),
])

edit("hlsl_codegen.c", [
    ('''        /* fxc2: a double takes two components. */
        if (type->e.numeric.type == HLSL_TYPE_DOUBLE && hlsl_version_ge(ctx, 4, 0))
            count = min(count * 2, 4);
        return allocate_register(ctx, allocator, count, count, 0, false, false, false);
''', '''        /* fxc2: a double takes two components, which have to be .xy or .zw;
         * aligning to the start of a register gives .xy. */
        if (type->e.numeric.type == HLSL_TYPE_DOUBLE && hlsl_version_ge(ctx, 4, 0))
        {
            count = min(count * 2, 4);
            return allocate_register(ctx, allocator, count, count, 0, true, false, false);
        }
        return allocate_register(ctx, allocator, count, count, 0, false, false, false);
'''),
])
print("patched allocator")

edit("tpf.c", [
    ('''        case VSIR_OP_ADD:
''', '''        case VSIR_OP_DADD:
        case VSIR_OP_DDIV:
        case VSIR_OP_DMOV:
        case VSIR_OP_DMUL:
        case VSIR_OP_DTOF:
        case VSIR_OP_DTOI:
        case VSIR_OP_DTOU:
        case VSIR_OP_FTOD:
        case VSIR_OP_ITOD:
        case VSIR_OP_UTOD:
        case VSIR_OP_ADD:
'''),
])
print("patched writer")

edit("hlsl_codegen.c", [
    ('''        instr->reg.writemask = vkd3d_write_mask_from_component_count(instr->data_type->e.numeric.dimx);
''', '''        /* fxc2: a double takes two components. */
        instr->reg.writemask = vkd3d_write_mask_from_component_count(
                instr->data_type->e.numeric.type == HLSL_TYPE_DOUBLE && hlsl_version_ge(ctx, 4, 0)
                ? min(instr->data_type->e.numeric.dimx * 2, 4) : instr->data_type->e.numeric.dimx);
''', 2),
])
print("patched ssa masks")

edit("hlsl.y", [
    ('''    if (!(type = elementwise_intrinsic_get_common_type(ctx, params, loc)))
        return false;
    if (hlsl_type_is_integer(type))
        type = hlsl_change_base_type(ctx, type, HLSL_TYPE_FLOAT);

    convert_args(ctx, params, type, loc);
    return true;
''', '''    if (!(type = elementwise_intrinsic_get_common_type(ctx, params, loc)))
        return false;
    /* fxc2: there are no double precision versions of floor(), sqrt() and
     * the like; FXC computes them in single precision, and so must we. */
    if (hlsl_type_is_integer(type) || type->e.numeric.type == HLSL_TYPE_DOUBLE)
        type = hlsl_change_base_type(ctx, type, HLSL_TYPE_FLOAT);

    convert_args(ctx, params, type, loc);
    return true;
'''),
])

edit("ir.c", [
    ('''    reg->written = true;
    reg->mask |= dst->write_mask;

    switch (opcode)
''', '''    reg->written = true;
    reg->mask |= dst->write_mask;

    /* fxc2: anything holding a double, however it is written. */
    if (dst->reg.data_type == VSIR_DATA_F64)
        reg->fixed_mask = true;

    switch (opcode)
'''),
])

edit("hlsl_codegen.c", [
    ('''    VKD3D_ASSERT(expr->node.reg.allocated);
    if (expr->operands[0].node)
        src_type = expr->operands[0].node->data_type;

    switch (expr->op)
    {
        case HLSL_OP0_RASTERIZER_SAMPLE_COUNT:''', '''    VKD3D_ASSERT(expr->node.reg.allocated);
    if (expr->operands[0].node)
        src_type = expr->operands[0].node->data_type;

    /* fxc2: never let a single precision instruction loose on a double. */
    if ((sm4_type_is_double(dst_type) || (src_type && sm4_type_is_double(src_type)))
            && expr->op != HLSL_OP1_CAST && expr->op != HLSL_OP1_NEG && expr->op != HLSL_OP2_ADD
            && expr->op != HLSL_OP2_MUL && expr->op != HLSL_OP2_DIV)
    {
        hlsl_fixme(ctx, &expr->node.loc, "SM5 double precision for expression op %#x.", expr->op);
        return false;
    }

    switch (expr->op)
    {
        case HLSL_OP0_RASTERIZER_SAMPLE_COUNT:'''),
])
print("patched demotion + guards")

edit("hlsl.y", [
    ('''    struct hlsl_type *type = arg->data_type;

    if (!hlsl_type_is_integer(type))
        return arg;

    type = hlsl_change_base_type(ctx, type, HLSL_TYPE_FLOAT);
    return add_implicit_conversion(ctx, params->instrs, arg, type, loc);
''', '''    struct hlsl_type *type = arg->data_type;

    /* fxc2: doubles are computed in single precision here, see
     * elementwise_intrinsic_float_convert_args(). */
    if (!hlsl_type_is_integer(type) && !(hlsl_is_numeric_type(type) && type->e.numeric.type == HLSL_TYPE_DOUBLE))
        return arg;

    type = hlsl_change_base_type(ctx, type, HLSL_TYPE_FLOAT);
    return add_implicit_conversion(ctx, params->instrs, arg, type, loc);
'''),
])
print("patched single-arg demotion")
