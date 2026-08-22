# The op vocabulary RV32I speaks (uop_contract.md §1.2). No catalog ships with
# the isa layer, so a description declares its own ops — see exec_unit.py's
# header for why. Names follow the §1.2 table so two ISAs that mean the same
# thing spell it the same way.
#
# The Ops are module CONSTANTS: value-equal, so sharing one couples nothing.
# Which UNITS execute them, and what they compute, is the sibling
# `exec_unit.py` — this file is the vocabulary alone, and importing it costs
# nothing else.
#
# Memory width/sign and branch condition are DISTINCT OPS, not sub-fields of
# one LOAD/STORE/BR_COND kind: lb/lh/lw/lbu/lhu, sb/sh/sw and
# beq/bne/blt/bge/bltu/bgeu each get their own Op, so the µop record needs no
# size/sign or condition field. AUIPC is likewise its own op, not an ADD with
# a PC source it has no way to name.

from __future__ import annotations

from ..op import Op

# --- integer ALU ------------------------------------------------------------
# `src2` is rs2 for the R-type form and the immediate for the I-type one: the
# op is the same operation either way, only the operand rule differs, so addi
# and add share ADD. All results wrap at 32 bits; RV32I traps on no
# arithmetic. Writes to x0 are discarded by rename, never by the FU.
ADD     = Op("ADD")         # rd = rs1 + src2            (add, addi)
SUB     = Op("SUB")         # rd = rs1 - src2            (sub; no subi — addi a negative)
AND     = Op("AND")         # rd = rs1 & src2            (and, andi)
OR      = Op("OR")          # rd = rs1 | src2            (or, ori)
XOR     = Op("XOR")         # rd = rs1 ^ src2            (xor, xori; xori -1 = not)
SLL     = Op("SLL")         # rd = rs1 << src2[4:0]      shift amount is 5 bits
SRL     = Op("SRL")         # rd = rs1 >> src2[4:0]      logical, zero-filled
SRA     = Op("SRA")         # rd = rs1 >> src2[4:0]      arithmetic, sign-filled
SLT     = Op("SLT")         # rd = (rs1 <  src2) ? 1 : 0 signed compare
SLTU    = Op("SLTU")        # rd = (rs1 <u src2) ? 1 : 0 unsigned (sltiu rd,rs,1 = seqz)
MOV_IMM = Op("MOV_IMM")     # rd = imm                   lui; imm is imm_u<<12, no src
AUIPC   = Op("AUIPC")       # rd = pc + imm              pc of THIS instr, imm_u<<12

# --- memory -----------------------------------------------------------------
# Address is always rs1 + imm, computed inside the unit. No AGU op: the
# address is not a value any second µop consumes — see the rv32i.py header.
# Width and sign live in the op, so no record sub-field carries them.
LB  = Op("LB")              # rd = sext8 (mem[rs1+imm])  1-byte load
LH  = Op("LH")              # rd = sext16(mem[rs1+imm])  2-byte load
LW  = Op("LW")              # rd =        mem[rs1+imm]   4-byte load, fills rd exactly
LBU = Op("LBU")             # rd = zext8 (mem[rs1+imm])  1-byte load, unsigned
LHU = Op("LHU")             # rd = zext16(mem[rs1+imm])  2-byte load, unsigned
SB  = Op("SB")              # mem[rs1+imm] = rs2[7:0]    1-byte store, no dest
SH  = Op("SH")              # mem[rs1+imm] = rs2[15:0]   2-byte store, no dest
SW  = Op("SW")              # mem[rs1+imm] = rs2         4-byte store, no dest

LOADS  = (LB, LH, LW, LBU, LHU)
STORES = (SB, SH, SW)

# --- control ----------------------------------------------------------------
# A branch reads two registers, writes none, and its effect is a redirect to
# pc+imm when the test holds (fall through to pc+ilen otherwise). The test is
# the op itself, so no cond-kind sub-field is needed.
BEQ          = Op("BEQ")            # taken if rs1 == rs2
BNE          = Op("BNE")            # taken if rs1 != rs2
BLT          = Op("BLT")            # taken if rs1 <  rs2   signed
BGE          = Op("BGE")            # taken if rs1 >= rs2   signed
BLTU         = Op("BLTU")           # taken if rs1 <  rs2   unsigned
BGEU         = Op("BGEU")           # taken if rs1 >= rs2   unsigned
# The jumps write the link register AND redirect, in one µop: rd = pc + ilen
# is not split out, so RV32I cracks nothing into more than one µop.
JMP          = Op("JMP")            # rd = pc + ilen; pc = pc + imm
                                    #   jal:  target known at decode
JMP_INDIRECT = Op("JMP_INDIRECT")   # rd = pc + ilen; pc = (rs1 + imm) & ~1
                                    #   jalr: target known at execute

BRANCHES = (BEQ, BNE, BLT, BGE, BLTU, BGEU)

# --- system -----------------------------------------------------------------
FENCE = Op("FENCE")                 # order earlier memory ops before later ones;
                                    # no register dataflow, no result
TRAP  = Op("TRAP")                  # ecall / ebreak: raise at commit, redirect to the
                                    # handler — the §6 trap policy will say to where

OPS = (ADD, SUB, AND, OR, XOR, SLL, SRL, SRA, SLT, SLTU, MOV_IMM, AUIPC,
       *LOADS, *STORES,
       *BRANCHES, JMP, JMP_INDIRECT,
       FENCE, TRAP)
