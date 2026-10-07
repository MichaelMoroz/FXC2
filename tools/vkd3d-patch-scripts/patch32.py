import os
base = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/")


def edit(name, pairs):
    path = base + name
    s = open(path).read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:80], s.count(old))
        s = s.replace(old, new)
    open(path, "w").write(s)


edit("hlsl_codegen.c", [
    ('''static bool is_same_vectorizable_expr(struct hlsl_ir_expr *a, struct hlsl_ir_expr *b)
''', '''/* fxc2: for stores, unlike for the operands of an expression, different
 * constants of one type will do as well: they can be written as one vector
 * constant, see vectorize_stores(). */
static bool is_same_vectorizable_store_source(struct hlsl_ir_node *a, struct hlsl_ir_node *b)
{
    if (a->type == HLSL_IR_CONSTANT && b->type == HLSL_IR_CONSTANT
            && a->data_type->e.numeric.type == b->data_type->e.numeric.type
            && a->data_type->e.numeric.type != HLSL_TYPE_DOUBLE)
        return true;
    return is_same_vectorizable_source(a, b);
}

static bool is_same_vectorizable_expr(struct hlsl_ir_expr *a, struct hlsl_ir_expr *b)
'''),
    ('''            if (group->block == block
                    && is_same_vectorizable_source(store->rhs.node, other->rhs.node))
''', '''            if (group->block == block
                    && is_same_vectorizable_store_source(store->rhs.node, other->rhs.node))
'''),
    ('''        struct hlsl_ir_store *store;
        struct hlsl_block new_block;

        if (group->store_count == 1)
            continue;
''', '''        struct hlsl_ir_store *store;
        struct hlsl_block new_block;
        bool all_constants;

        if (group->store_count == 1)
            continue;
'''),
    ('''        store = group->stores[0];
        value = store->rhs.node;
        if (value->type == HLSL_IR_SWIZZLE)
            value = hlsl_ir_swizzle(value)->val.node;

        new_rhs = hlsl_block_add_swizzle(ctx, &new_block, new_swizzle, component_count, value, &value->loc);
''', '''        store = group->stores[0];
        value = store->rhs.node;
        if (value->type == HLSL_IR_SWIZZLE)
            value = hlsl_ir_swizzle(value)->val.node;

        all_constants = true;
        for (unsigned int j = 0; j < group->store_count; ++j)
        {
            if (group->stores[j]->rhs.node->type != HLSL_IR_CONSTANT)
                all_constants = false;
        }

        if (all_constants)
        {
            /* fxc2: "float4(1, 1, 1, x)" stores three constants, which may
             * well be three different nodes. Make one constant of them; later
             * stores win where they overlap, as they would have done. */
            struct hlsl_constant_value constant = {0}, by_component = {0};
            unsigned int count = 0;

            for (unsigned int j = 0; j < group->store_count; ++j)
            {
                const struct hlsl_ir_constant *c = hlsl_ir_constant(group->stores[j]->rhs.node);
                unsigned int n = 0;

                for (unsigned int k = 0; k < 4; ++k)
                {
                    if (group->writemasks[j] & (1u << k))
                        by_component.u[k] = c->value.u[min(n++, c->node.data_type->e.numeric.dimx - 1)];
                }
            }
            for (unsigned int k = 0; k < 4; ++k)
            {
                if (new_writemask & (1u << k))
                    constant.u[count++] = by_component.u[k];
            }
            new_rhs = hlsl_block_add_constant(ctx, &new_block, hlsl_get_vector_type(ctx,
                    value->data_type->e.numeric.type, count), &constant, &value->loc);
        }
        else
        new_rhs = hlsl_block_add_swizzle(ctx, &new_block, new_swizzle, component_count, value, &value->loc);
'''),
])

edit("ir.c", [
    ('''        for (unsigned int j = 0; j < ins->dst_count; ++j)
            temp_allocator_set_dst(&allocator, &ins->dst[j], ins);
    }

    program->ssa_count = 0;
''', '''        for (unsigned int j = 0; j < ins->dst_count; ++j)
            temp_allocator_set_dst(&allocator, &ins->dst[j], ins);

        /* fxc2: a value and its copy often end up in the same register,
         * which leaves "mov r1.xyzw, r1.xyzw". */
        if (ins->opcode == VSIR_OP_MOV && ins->dst[0].reg.type == VSIR_REGISTER_TEMP
                && ins->src[0].reg.type == VSIR_REGISTER_TEMP
                && ins->dst[0].reg.idx[0].offset == ins->src[0].reg.idx[0].offset
                && !ins->dst[0].modifiers && !ins->src[0].modifiers)
        {
            bool identity = true;

            for (unsigned int j = 0; j < 4; ++j)
            {
                if ((ins->dst[0].write_mask & (1u << j)) && vsir_swizzle_get_component(ins->src[0].swizzle, j) != j)
                    identity = false;
            }
            if (identity)
                vsir_instruction_make_nop(ins);
        }
    }

    program->ssa_count = 0;
'''),
])
print("patched")
