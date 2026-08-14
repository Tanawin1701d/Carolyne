# RV32I description package — a TEMPLATE skeleton, not a finished ISA.
#
# It supplies the deliverables of uop_contract.md §6 that have types today:
#   reg.py     — architectural register classes (§6.1); x only, PC is not one
#   op.py      — op vocabulary + the machine's execution units (§1.2)
#   field_match.py — where each encoding field lives in the 32-bit word
#                (§6.2), and ILEN_BYTES, standing in for the length decoder (§6.3)
#   operand.py — the rd/rs1/rs2 index rules and the six immediate rules,
#                bound to those field positions (OPR_* constants)
#   uop.py     — one µop template per instruction of the RV32I listing (§6.4)
#   rv32i.py   — the Mop table binding encodings to those templates, and the
#                IsaBase assembly
# Not supplied: the trap policy (§6.5), which has no type yet.
#
# The operand rules are module constants, so the register class they target
# is one too: `reg.RegFile`, built by `x_file()` and shared by every shape
# and by the `reg_files=(RegFile,)` the description declares. IsaBase matches reg files by
# IDENTITY, and sharing constants is what makes those the same object.
# Consequence: two rv32i() builds share it — call `x_file()` and build your own
# operands if you need genuinely independent descriptions. `exec_units()` and
# `mop_table()` stay functions; nothing mutates any of it.
#
# Every file carries a KNOWN GAPS block naming what it cannot express. The
# short version: field matchers have no values, Uop has no immediate, and PC
# is not nameable as a µop input — so this package proves the SHAPES fit the
# contract and the container's cross-checks pass, not that RV32I can be
# decoded. Those gaps are
# contract-side; fixing them must not touch uarch.
#
# Rules this package obeys (CLAUDE.md §3): description data only, no hardware
# code, no Kathryn import, and no import from carolyne.uarch.

from __future__ import annotations

from .field_match import ILEN_BYTES
from .operand import (OPR_IMM_B, OPR_IMM_I, OPR_IMM_J, OPR_IMM_S, OPR_IMM_U,
                      OPR_IMM_SHAMT, OPR_IMMS, OPR_RD, OPR_REGS, OPR_RS1,
                      OPR_RS2)
from .op import OPS, exec_units
from .reg import ImmTarget, RegFile, X_LEN, x_file
from .rv32i import mop_table, rv32i
from .uop import UOPS

__all__ = [
    "rv32i", "mop_table", "OPS", "exec_units", "ILEN_BYTES",
    "RegFile", "ImmTarget", "X_LEN", "x_file",
    "OPR_RD", "OPR_RS1", "OPR_RS2", "OPR_REGS",
    "OPR_IMM_I", "OPR_IMM_S", "OPR_IMM_B", "OPR_IMM_U", "OPR_IMM_J",
    "OPR_IMM_SHAMT", "OPR_IMMS", "UOPS",
]
