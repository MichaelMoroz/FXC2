import os
p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl_codegen.c")
s = open(p).read()


def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


rep('''static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{''', '''/* fxc2: what an expression counts for when deciding whether a block is small
 * enough to run unconditionally. A sine is not an addition: "if (angle != 0)
 * { rotate }" as a select computes the sine and cosine for every pixel. */
static unsigned int flatten_expr_cost(const struct hlsl_ir_expr *expr)
{
    switch (expr->op)
    {
        case HLSL_OP1_COS:
        case HLSL_OP1_COS_REDUCED:
        case HLSL_OP1_SIN:
        case HLSL_OP1_SIN_REDUCED:
        case HLSL_OP1_EXP2:
        case HLSL_OP1_LOG2:
            return 6;

        case HLSL_OP1_RCP:
        case HLSL_OP1_RSQ:
        case HLSL_OP1_SQRT:
        case HLSL_OP2_DIV:
        case HLSL_OP2_MOD:
            return 3;

        default:
            return 1;
    }
}

static bool is_conditional_block_simple(const struct hlsl_block *cond_block)
{''')
rep('''            case HLSL_IR_EXPR:
                ++cost;
                break;

            case HLSL_IR_JUMP:
            {
                struct hlsl_ir_jump *jump = hlsl_ir_jump(instr);

                if (jump->type != HLSL_IR_JUMP_DISCARD_NZ && jump->type != HLSL_IR_JUMP_DISCARD_NEG)
                    return false;
                ++cost;''', '''            case HLSL_IR_EXPR:
                cost += flatten_expr_cost(hlsl_ir_expr(instr));
                break;

            case HLSL_IR_JUMP:
            {
                struct hlsl_ir_jump *jump = hlsl_ir_jump(instr);

                if (jump->type != HLSL_IR_JUMP_DISCARD_NZ && jump->type != HLSL_IR_JUMP_DISCARD_NEG)
                    return false;
                ++cost;''')
assert "HLSL_OP1_COS_REDUCED" in open(os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/hlsl.h")).read()
open(p, "w").write(s)

p = os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/ir.c")
s = open(p).read()
PASS = r'''/* fxc2: sin(x) and cos(x) are one instruction with two results:
 *
 *     sincos null, sr1.x, sr0.x
 *     sincos sr2.x, null, sr0.x          sincos sr2.x, sr1.x, sr0.x
 *
 * The HLSL side writes one for each call; FXC writes one for the pair. */
static bool forward_opcode_is_flow(enum vsir_opcode opcode)
{
    switch (opcode)
    {
        case VSIR_OP_BREAK:
        case VSIR_OP_BREAKC:
        case VSIR_OP_BREAKP:
        case VSIR_OP_CASE:
        case VSIR_OP_CONTINUE:
        case VSIR_OP_CONTINUEP:
        case VSIR_OP_DEFAULT:
        case VSIR_OP_ELSE:
        case VSIR_OP_ENDIF:
        case VSIR_OP_ENDLOOP:
        case VSIR_OP_ENDSWITCH:
        case VSIR_OP_IF:
        case VSIR_OP_IFC:
        case VSIR_OP_LABEL:
        case VSIR_OP_LOOP:
        case VSIR_OP_RET:
        case VSIR_OP_SWITCH:
            return true;

        default:
            return false;
    }
}

static void vsir_program_merge_sincos(struct vsir_program *program, struct vsir_instruction **list,
        unsigned int count)
{
    const char *env;

    if (program->shader_version.major < 4 || ((env = getenv("VKD3D_MERGE_SINCOS")) && !strcmp(env, "0")))
        return;

    for (unsigned int i = 0; i < count; ++i)
    {
        struct vsir_instruction *a = list[i];
        unsigned int free_slot;

        if (a->opcode != VSIR_OP_SINCOS || a->dst_count != 2 || a->src_count != 1
                || a->src[0].reg.type != VSIR_REGISTER_SSA || a->src[0].modifiers)
            continue;
        if (a->dst[0].reg.type == VSIR_REGISTER_NULL && a->dst[1].reg.type != VSIR_REGISTER_NULL)
            free_slot = 0;
        else if (a->dst[1].reg.type == VSIR_REGISTER_NULL && a->dst[0].reg.type != VSIR_REGISTER_NULL)
            free_slot = 1;
        else
            continue;

        for (unsigned int j = i + 1; j < count && j < i + 16; ++j)
        {
            struct vsir_instruction *b = list[j];

            if (forward_opcode_is_flow(b->opcode))
                break;
            if (b->opcode != VSIR_OP_SINCOS || b->dst_count != 2 || b->src_count != 1)
                continue;
            if (b->src[0].reg.type != VSIR_REGISTER_SSA || b->src[0].modifiers
                    || b->src[0].reg.idx[0].offset != a->src[0].reg.idx[0].offset
                    || b->src[0].swizzle != a->src[0].swizzle
                    || b->dst[!free_slot].reg.type != VSIR_REGISTER_NULL
                    || b->dst[free_slot].reg.type != VSIR_REGISTER_SSA
                    || b->dst[free_slot].write_mask != a->dst[!free_slot].write_mask)
                continue;
            a->dst[free_slot] = b->dst[free_slot];
            vsir_instruction_make_nop(b);
            break;
        }
    }
}

'''
anchor = "/* fxc2: a field of a word is a shift and a mask in HLSL and one instruction in"
rep(anchor, PASS + anchor)
rep('''    vsir_program_fold_bitfield_extracts(program, list, count, ssa);
''', '''    vsir_program_merge_sincos(program, list, count);
    vsir_program_fold_bitfield_extracts(program, list, count, ssa);
''')
for name in ("VSIR_OP_BREAKP", "VSIR_OP_CONTINUEP", "VSIR_OP_IFC", "VSIR_OP_BREAKC", "VSIR_OP_LABEL", "VSIR_REGISTER_NULL"):
    assert name in open(os.path.expanduser("~/fxc2/vkd3d/libs/vkd3d-shader/vkd3d_shader_private.h")).read(), name
open(p, "w").write(s)
print("patched")
