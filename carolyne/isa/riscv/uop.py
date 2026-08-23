# One Uop template per RV32I instruction — the µop an instruction decodes to,
# transcribed from the RV32I base listing (RISC-V unprivileged spec, ch. 36).
# Every instruction is exactly ONE µop here: RV32I has no AGU (addressing is
# base+imm, computed in the mem unit) and no separate link µop (the jumps
# write rd themselves), so nothing cracks. See the rv32i.py header.
#
# Module CONSTANTS named UOP_<mnemonic>, one per row of the listing, so this
# file is the one place an instruction is written down and rv32i.py is purely
# the opcode grouping. Each template NAMES ITSELF — the mnemonic is the µop's
# own name, unique across the ISA, and the hardware plane speaks it as
# `uop_idx`. There is no op vocabulary beside this file: an `Op` type held a
# name and nothing else, so the name moved onto the template that has the rest
# of the operation (uop.py, 2026-08-23). ADDI is therefore its own µop rather
# than "ADD with the other second-operand rule", and a stage body that means
# both guards on both.
#
# Each template declares its own matcher: the funct field that picks it out of
# its opcode group, plus the value that field must equal (`FM.val(...)`, one
# value per segment, in the field's own segment order). Where an instruction
# needs BOTH funct3 and funct7 (add vs sub, srl vs sra, the shift-immediates)
# it names FM.FUNCT3_7, one rule spanning both fields. LUI/AUIPC/JAL name no
# field and no value: their opcode alone identifies them, and the opcode is
# the Mop's rule.
#
# Width, sign and branch condition are distinct µops, not sub-fields of one
# LOAD/STORE/BR_COND kind, so the file is 1:1 with the listing and the record
# needs no size/sign or condition field: lb/lh/lw/lbu/lhu, sb/sh/sw and
# beq/bne/blt/bge/bltu/bgeu each get their own template. AUIPC is likewise its
# own µop, not an ADD with a PC source it has no way to name.
# ADDI/SLTI/... differ from their register forms only in the second operand
# rule; SLLI/SRLI/SRAI take SHAMT rather than IMM_I, a 5-bit count instead of
# a 12-bit signed value. All results wrap at 32 bits; RV32I traps on no
# arithmetic, and writes to x0 are discarded by rename, never by the FU.
#
# The immediate rides in `srcs` as an operand (OPR_IMM_*) because `Uop.imm`
# does not exist yet. NOTE the tension: contract §2 says an immediate is NOT
# an operand and rides in its own record field, so the ≤3 src cap does not
# budget for one. RV32I still fits (store and branch are widest, at 3).
#
# The instruction's own PC is never among the srcs: no operand can name it
# (reg.py: PC is not a register class), and none needs to — the µop record
# carries it and a stage body reads it as ctx.pc() (isa/exec_context.py), which
# is how auipc, jal and jalr get their pc-relative input.
#
# KNOWN GAPS carried from the layer below:
# - A value says WHICH BITS but not where each segment lands in an assembled
#   field, so the funct matchers here are complete but the immediate
#   *extractors* still are not (field_match.py). Discriminating works;
#   building the immediate value does not.
# - The branch/jump redirect is not expressed: the control FU takes it from
#   the op plus the immediate, and no dest names it.

from __future__ import annotations

from ..uop import Uop
from . import field_match as FM
from .operand import (OPR_IMM_B, OPR_IMM_I, OPR_IMM_J, OPR_IMM_S,
                      OPR_IMM_SHAMT, OPR_IMM_U, OPR_RD, OPR_RS1, OPR_RS2)

_RD    = (OPR_RD,)
_BR    = (OPR_RS1, OPR_RS2, OPR_IMM_B)      # branch: two compares + target
_ADDR  = (OPR_RS1, OPR_IMM_I)               # load:   base + displacement
_STORE = (OPR_RS1, OPR_RS2, OPR_IMM_S)      # store:  base + data + displacement
_IMM   = (OPR_RS1, OPR_IMM_I)               # op-imm: register + 12-bit signed
_SHIFT = (OPR_RS1, OPR_IMM_SHAMT)           # shift-imm: register + 5-bit count
_REG   = (OPR_RS1, OPR_RS2)                 # op:     two registers

# --- U-type, opcode 0110111 / 0010111: rd = imm ------------------------------
# No funct field: the opcode alone identifies these, so no matcher at all.
UOP_LUI   = Uop("LUI",   srcs=(OPR_IMM_U,), dests=_RD)   # rd = imm_u << 12
UOP_AUIPC = Uop("AUIPC", srcs=(OPR_IMM_U,), dests=_RD)   # rd = pc + (imm_u << 12)

# --- jumps, opcode 1101111 / 1100111: rd = pc + ilen, then redirect ----------
# rd = pc + ilen, then redirect: jal to pc + imm (target known at decode),
# jalr to (rs1 + imm) & ~1 (known at execute). One µop, so nothing cracks.
UOP_JAL  = Uop("JAL",  srcs=(OPR_IMM_J,), dests=_RD)                  # opcode alone
UOP_JALR = Uop("JALR", srcs=_ADDR, dests=_RD,
               matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))

# --- B-type, opcode 1100011: redirect when the test holds, no destination ----
UOP_BEQ  = Uop("BEQ",  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_BNE  = Uop("BNE",  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_BLT  = Uop("BLT",  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_BGE  = Uop("BGE",  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b101))
UOP_BLTU = Uop("BLTU", srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b110))
UOP_BGEU = Uop("BGEU", srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b111))

BRANCHES = (UOP_BEQ, UOP_BNE, UOP_BLT, UOP_BGE, UOP_BLTU, UOP_BGEU)

# --- I-type loads, opcode 0000011: rd = mem[rs1 + imm] -----------------------
UOP_LB  = Uop("LB",  srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_LH  = Uop("LH",  srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_LW  = Uop("LW",  srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))
UOP_LBU = Uop("LBU", srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_LHU = Uop("LHU", srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b101))

LOADS = (UOP_LB, UOP_LH, UOP_LW, UOP_LBU, UOP_LHU)

# --- S-type stores, opcode 0100011: mem[rs1 + imm] = rs2 ---------------------
UOP_SB = Uop("SB", srcs=_STORE, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_SH = Uop("SH", srcs=_STORE, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_SW = Uop("SW", srcs=_STORE, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))

STORES = (UOP_SB, UOP_SH, UOP_SW)

# --- I-type ALU, opcode 0010011: rd = rs1 op imm -----------------------------
UOP_ADDI  = Uop("ADDI",  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_SLTI  = Uop("SLTI",  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))
UOP_SLTIU = Uop("SLTIU", srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b011))
UOP_XORI  = Uop("XORI",  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_ORI   = Uop("ORI",   srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b110))
UOP_ANDI  = Uop("ANDI",  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b111))

# Shift-immediate: funct3 picks the direction, funct7 logical vs arithmetic.
# Two segments in FUNCT3_7, so two values, funct3 first — that is the order
# FUNCT3_7 was unioned in (field_match.py).
UOP_SLLI = Uop("SLLI", srcs=_SHIFT, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b001, 0b0000000))
UOP_SRLI = Uop("SRLI", srcs=_SHIFT, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0000000))
UOP_SRAI = Uop("SRAI", srcs=_SHIFT, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0100000))

# --- R-type, opcode 0110011: rd = rs1 op rs2 ---------------------------------
UOP_ADD  = Uop("ADD",  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b000, 0b0000000))
UOP_SUB  = Uop("SUB",  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b000, 0b0100000))
UOP_SLL  = Uop("SLL",  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_SLT  = Uop("SLT",  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))
UOP_SLTU = Uop("SLTU", srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b011))
UOP_XOR  = Uop("XOR",  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_SRL  = Uop("SRL",  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0000000))
UOP_SRA  = Uop("SRA",  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0100000))
UOP_OR   = Uop("OR",   srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b110))
UOP_AND  = Uop("AND",  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b111))

# --- outside the base listing above, but part of RV32I -----------------------
# ecall and ebreak share opcode 1110011 AND funct3 000; the whole imm[11:0] is
# what tells them apart, which is why their matcher is IMM_I and not FUNCT3.
# fence orders earlier memory ops before later ones: no register dataflow and
# no result. ecall/ebreak raise at commit and redirect to the handler — where
# to is the §6 trap policy, which has no type yet.
UOP_FENCE  = Uop("FENCE", matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_ECALL  = Uop("ECALL",  matcher_field=FM.IMM_I, matcher_value=FM.val(0b000000000000))
UOP_EBREAK = Uop("EBREAK",  matcher_field=FM.IMM_I, matcher_value=FM.val(0b000000000001))

UOPS = (UOP_LUI, UOP_AUIPC, UOP_JAL, UOP_JALR,
        UOP_BEQ, UOP_BNE, UOP_BLT, UOP_BGE, UOP_BLTU, UOP_BGEU,
        UOP_LB, UOP_LH, UOP_LW, UOP_LBU, UOP_LHU,
        UOP_SB, UOP_SH, UOP_SW,
        UOP_ADDI, UOP_SLTI, UOP_SLTIU, UOP_XORI, UOP_ORI, UOP_ANDI,
        UOP_SLLI, UOP_SRLI, UOP_SRAI,
        UOP_ADD, UOP_SUB, UOP_SLL, UOP_SLT, UOP_SLTU, UOP_XOR,
        UOP_SRL, UOP_SRA, UOP_OR, UOP_AND,
        UOP_FENCE, UOP_ECALL, UOP_EBREAK)
