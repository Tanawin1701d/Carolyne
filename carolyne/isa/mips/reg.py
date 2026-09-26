# MIPS32 architectural register classes (uop_contract.md §1.1 / §6 deliverable
# one), plus the target an immediate operand points at. Description data
# only — no hardware, no Kathryn.
#
# Three renamed classes:
#   r    $0..$31, X_LEN bits; $0 is declared through `const_regs`, so rename
#        bypasses reads of it and discards writes to it (nop is `sll $0,$0,0`)
#   hi   the multiply/divide accumulator's high word: ONE register, so an
#        operand on it carries no index (Operand's one-register rule)
#   lo   its low word, the same shape
# HI and LO are two classes rather than one 64-bit value: MFHI/MFLO read one
# of them and MTHI/MTLO write one, and two classes give each its own rename
# port while MULT/DIV write both as one µop's two destinations.
#
# PC is NOT a register class: the µop record carries it and a stage body
# reads it off that record — the link value, a branch target and a jump's
# region all come from there.
#
# `GPR_FILE`, `HI_FILE` and `LO_FILE` are module-level SHARED INSTANCES with their builders
# beside them, because IsaBase matches register files by identity and the
# operand rules that target them are module constants too.

from __future__ import annotations

from ..reg import Intermediate, RegFile

X_LEN = 32                  # register width; MIPS32 by definition
SIGN  = 1 << (X_LEN - 1)    # the sign bit, for signed-order tricks


def build_gpr_file() -> RegFile: return RegFile("r" , X_LEN, 32, const_regs={0: 0})
def build_hi_file()  -> RegFile: return RegFile("hi", X_LEN, 1)
def build_lo_file()  -> RegFile: return RegFile("lo", X_LEN, 1)


GPR_FILE   = build_gpr_file()               # the instances operands and the ISA share
HI_FILE    = build_hi_file()
LO_FILE    = build_lo_file()
IMM_TARGET = Intermediate(X_LEN, "imm")     # what an immediate operand targets
