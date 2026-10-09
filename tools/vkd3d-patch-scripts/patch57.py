import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


rep('''/* Whether the node is of a kind this pass handles, and its hash if so. */
static bool lvn_hash_node(const struct hlsl_ir_node *instr, uint32_t *hash)
{''', '''/* fxc2: a texture sample is the dearest thing a material shader does, and
 * inlined helpers ask for the same one again (a Poiyomi variant had 35 where
 * FXC's build has 30). Sampling is of read-only textures, so two samples of
 * one texture with one sampler at the same coordinates are one value. Loads
 * are left alone: a Load may be of something the shader writes. */
static bool lvn_resource_load_is_pure(const struct hlsl_ir_resource_load *load)
{
    switch (load->load_type)
    {
        case HLSL_RESOURCE_SAMPLE:
        case HLSL_RESOURCE_SAMPLE_CMP:
        case HLSL_RESOURCE_SAMPLE_CMP_LZ:
        case HLSL_RESOURCE_SAMPLE_GRAD:
        case HLSL_RESOURCE_SAMPLE_LOD:
        case HLSL_RESOURCE_SAMPLE_LOD_BIAS:
            break;

        default:
            return false;
    }
    return load->resource.var && load->resource.var->is_uniform
            && load->sampler.var && load->sampler.var->is_uniform;
}

static const struct hlsl_src *lvn_resource_load_src(const struct hlsl_ir_resource_load *load, unsigned int i)
{
    const struct hlsl_src *srcs[] = {&load->byte_offset, &load->coords, &load->lod, &load->ddx, &load->ddy,
            &load->cmp, &load->sample_index, &load->texel_offset};

    return i < ARRAY_SIZE(srcs) ? srcs[i] : NULL;
}

static bool lvn_derefs_equal(const struct hlsl_deref *a, const struct hlsl_deref *b)
{
    unsigned int i;

    if (a->var != b->var || a->path_len != b->path_len)
        return false;
    for (i = 0; i < a->path_len; ++i)
    {
        if (a->path[i].node != b->path[i].node)
            return false;
    }
    return true;
}

/* Whether the node is of a kind this pass handles, and its hash if so. */
static bool lvn_hash_node(const struct hlsl_ir_node *instr, uint32_t *hash)
{''')

rep('''            h = lvn_hash_combine(h, (uintptr_t)deref->var);
            for (i = 0; i < deref->path_len; ++i)
                h = lvn_hash_combine(h, (uintptr_t)deref->path[i].node);
            break;
        }

        default:
            return false;
    }

    *hash = h;
    return true;
}''', '''            h = lvn_hash_combine(h, (uintptr_t)deref->var);
            for (i = 0; i < deref->path_len; ++i)
                h = lvn_hash_combine(h, (uintptr_t)deref->path[i].node);
            break;
        }

        case HLSL_IR_RESOURCE_LOAD:
        {
            const struct hlsl_ir_resource_load *load = hlsl_ir_resource_load(instr);
            const struct hlsl_src *src;

            if (!lvn_resource_load_is_pure(load))
                return false;
            h = lvn_hash_combine(h, load->load_type * 16 + load->sampling_dim);
            h = lvn_hash_combine(h, (uintptr_t)load->resource.var);
            h = lvn_hash_combine(h, (uintptr_t)load->sampler.var);
            for (i = 0; (src = lvn_resource_load_src(load, i)); ++i)
                h = lvn_hash_combine(h, (uintptr_t)src->node);
            break;
        }

        default:
            return false;
    }

    *hash = h;
    return true;
}''')

rep('''            for (i = 0; i < da->path_len; ++i)
            {
                if (da->path[i].node != db->path[i].node)
                    return false;
            }
            return true;
        }

        default:
            return false;
    }
}''', '''            for (i = 0; i < da->path_len; ++i)
            {
                if (da->path[i].node != db->path[i].node)
                    return false;
            }
            return true;
        }

        case HLSL_IR_RESOURCE_LOAD:
        {
            const struct hlsl_ir_resource_load *la = hlsl_ir_resource_load(a), *lb = hlsl_ir_resource_load(b);
            const struct hlsl_src *src;

            if (la->load_type != lb->load_type || la->sampling_dim != lb->sampling_dim
                    || !lvn_derefs_equal(&la->resource, &lb->resource)
                    || !lvn_derefs_equal(&la->sampler, &lb->sampler))
                return false;
            for (i = 0; (src = lvn_resource_load_src(la, i)); ++i)
            {
                if (src->node != lvn_resource_load_src(lb, i)->node)
                    return false;
            }
            return true;
        }

        default:
            return false;
    }
}''')
open(p, "w").write(s)
print("patched")
