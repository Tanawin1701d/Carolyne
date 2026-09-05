# One Uop template per RV32I instruction — the µop an instruction decodes to,
# transcribed from the RV32I base listing (RISC-V unprivileged spec, ch. 36).
# Every instruction is exactly ONE µop here: RV32I has no AGU (addressing is
# base+imm, computed in the mem unit) and no separate link µop (the jumps
# write rd themselves), so nothing cracks. See the rv32i.py header.
#
# Module CONSTANTS named UOP_<mnemonic>, one per row of the listing, so this
# file is the one place an instruction is written down and rv32i.py is purely
# the opcode grouping. Each template NAMES ITSELF — the mnemonic is the µop's
# own name, unique across the ISA — and DECLARES ITS ID: the second argument
# is `uop_idx`, the value the hardware plane speaks, 0..39 here in the order
# the UOPS tuple lists them. IsaBase holds the ids unique and dense; the tuple
# order itself means nothing to hardware. There is no op vocabulary beside
# this file: an `Op` type held a name and nothing else, so the name moved onto
# the template that has the rest of the operation (uop.py, 2026-08-23). ADDI
# is therefore its own µop rather than "ADD with the other second-operand
# rule", and a stage body that means both guards on both.
#
# A template carries NO matcher: picking an instruction out of the word is
# the ENCODING side's job, and the funct rules live on the UopSeq variants in
# mop.py beside the opcode they refine. A template names the operation only —
# which is why ecall and ebreak are equal here but for name and id.
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
# carries it and a stage body reads it as ctx.pc() off the generator's context, which
# is how auipc, jal and jalr get their pc-relative input.
#
# KNOWN GAPS carried from the layer below:
# - A value says WHICH BITS but not where each segment lands in an assembled
#   field, so the mop table discriminates but the immediate *extractors*
#   still do not exist (field_match.py). Picking works; building the
#   immediate value does not.
# - The branch/jump redirect is not expressed: the control FU takes it from
#   the op plus the immediate, and no dest names it.

from __future__ import annotations

from ..uop import Uop
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
UOP_LUI   = Uop("LUI",   0, srcs=(OPR_IMM_U,), dests=_RD)   # rd = imm_u << 12
UOP_AUIPC = Uop("AUIPC", 1, srcs=(OPR_IMM_U,), dests=_RD)   # rd = pc + (imm_u << 12)

# What a µop IS to the machine, beyond its operands. The ENGINE decides what
# each means — the ROB groups its commit barrier on both, and the store buffer
# pops on _STORE (uop_contract: the ISA states the fact, the generator builds
# the hardware).
_FEAT_BRANCH = ("is_branch",)   # augments the pc: the ROB's barrier reads it
_FEAT_STORE  = ("is_store",)    # reaches memory only on retirement

# --- jumps, opcode 1101111 / 1100111: rd = pc + ilen, then redirect ----------
# rd = pc + ilen, then redirect: jal to pc + imm (target known at decode),
# jalr to (rs1 + imm) & ~1 (known at execute). One µop, so nothing cracks.
UOP_JAL  = Uop("JAL",  2, srcs=(OPR_IMM_J,), dests=_RD,
                specified_feature=_FEAT_BRANCH)
UOP_JALR = Uop("JALR", 3, srcs=_ADDR, dests=_RD,
                specified_feature=_FEAT_BRANCH)

# --- B-type, opcode 1100011: redirect when the test holds, no destination ----
UOP_BEQ  = Uop("BEQ",  4, srcs=_BR, specified_feature=_FEAT_BRANCH)
UOP_BNE  = Uop("BNE",  5, srcs=_BR, specified_feature=_FEAT_BRANCH)
UOP_BLT  = Uop("BLT",  6, srcs=_BR, specified_feature=_FEAT_BRANCH)
UOP_BGE  = Uop("BGE",  7, srcs=_BR, specified_feature=_FEAT_BRANCH)
UOP_BLTU = Uop("BLTU", 8, srcs=_BR, specified_feature=_FEAT_BRANCH)
UOP_BGEU = Uop("BGEU", 9, srcs=_BR, specified_feature=_FEAT_BRANCH)

BRANCHES = (UOP_BEQ, UOP_BNE, UOP_BLT, UOP_BGE, UOP_BLTU, UOP_BGEU)

# --- I-type loads, opcode 0000011: rd = mem[rs1 + imm] -----------------------
UOP_LB  = Uop("LB",  10, srcs=_ADDR, dests=_RD)
UOP_LH  = Uop("LH",  11, srcs=_ADDR, dests=_RD)
UOP_LW  = Uop("LW",  12, srcs=_ADDR, dests=_RD)
UOP_LBU = Uop("LBU", 13, srcs=_ADDR, dests=_RD)
UOP_LHU = Uop("LHU", 14, srcs=_ADDR, dests=_RD)

LOADS = (UOP_LB, UOP_LH, UOP_LW, UOP_LBU, UOP_LHU)

# --- S-type stores, opcode 0100011: mem[rs1 + imm] = rs2 ---------------------
UOP_SB = Uop("SB", 15, srcs=_STORE, specified_feature=_FEAT_STORE)
UOP_SH = Uop("SH", 16, srcs=_STORE, specified_feature=_FEAT_STORE)
UOP_SW = Uop("SW", 17, srcs=_STORE, specified_feature=_FEAT_STORE)

STORES = (UOP_SB, UOP_SH, UOP_SW)

# --- I-type ALU, opcode 0010011: rd = rs1 op imm -----------------------------
UOP_ADDI  = Uop("ADDI",  18, srcs=_IMM, dests=_RD)
UOP_SLTI  = Uop("SLTI",  19, srcs=_IMM, dests=_RD)
UOP_SLTIU = Uop("SLTIU", 20, srcs=_IMM, dests=_RD)
UOP_XORI  = Uop("XORI",  21, srcs=_IMM, dests=_RD)
UOP_ORI   = Uop("ORI",   22, srcs=_IMM, dests=_RD)
UOP_ANDI  = Uop("ANDI",  23, srcs=_IMM, dests=_RD)

# Shift-immediate: SHAMT rather than IMM_I — a 5-bit count, not a 12-bit value.
UOP_SLLI = Uop("SLLI", 24, srcs=_SHIFT, dests=_RD)
UOP_SRLI = Uop("SRLI", 25, srcs=_SHIFT, dests=_RD)
UOP_SRAI = Uop("SRAI", 26, srcs=_SHIFT, dests=_RD)

# --- R-type, opcode 0110011: rd = rs1 op rs2 ---------------------------------
UOP_ADD  = Uop("ADD",  27, srcs=_REG, dests=_RD)
UOP_SUB  = Uop("SUB",  28, srcs=_REG, dests=_RD)
UOP_SLL  = Uop("SLL",  29, srcs=_REG, dests=_RD)
UOP_SLT  = Uop("SLT",  30, srcs=_REG, dests=_RD)
UOP_SLTU = Uop("SLTU", 31, srcs=_REG, dests=_RD)
UOP_XOR  = Uop("XOR",  32, srcs=_REG, dests=_RD)
UOP_SRL  = Uop("SRL",  33, srcs=_REG, dests=_RD)
UOP_SRA  = Uop("SRA",  34, srcs=_REG, dests=_RD)
UOP_OR   = Uop("OR",   35, srcs=_REG, dests=_RD)
UOP_AND  = Uop("AND",  36, srcs=_REG, dests=_RD)

# --- outside the base listing above, but part of RV32I -----------------------
# fence orders earlier memory ops before later ones: no register dataflow and
# no result. ecall/ebreak raise at commit and redirect to the handler — where
# to is the §6 trap policy, which has no type yet. What tells ecall from
# ebreak is their UopSeq's IMM_I value (mop.py).
UOP_FENCE  = Uop("FENCE",  37)
UOP_ECALL  = Uop("ECALL",  38)
UOP_EBREAK = Uop("EBREAK", 39)

UOPS = (UOP_LUI, UOP_AUIPC, UOP_JAL, UOP_JALR,
        UOP_BEQ, UOP_BNE, UOP_BLT, UOP_BGE, UOP_BLTU, UOP_BGEU,
        UOP_LB, UOP_LH, UOP_LW, UOP_LBU, UOP_LHU,
        UOP_SB, UOP_SH, UOP_SW,
        UOP_ADDI, UOP_SLTI, UOP_SLTIU, UOP_XORI, UOP_ORI, UOP_ANDI,
        UOP_SLLI, UOP_SRLI, UOP_SRAI,
        UOP_ADD, UOP_SUB, UOP_SLL, UOP_SLT, UOP_SLTU, UOP_XOR,
        UOP_SRL, UOP_SRA, UOP_OR, UOP_AND,
        UOP_FENCE, UOP_ECALL, UOP_EBREAK)
