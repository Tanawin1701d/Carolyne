# RV32I description package — a TEMPLATE skeleton, not a finished ISA.
#
# It supplies the deliverables of uop_contract.md §6 that have types today:
#   reg.py     — architectural register classes (§6.1); x only, PC is not one
#   op.py      — op vocabulary + the machine's execution units (§1.2)
#   field_match.py — where each encoding field lives in the 32-bit word
#                (§6.2), the six base formats as unions of those fields, and
#                ILEN_BYTES, standing in for the length decoder (§6.3)
#   operand.py — the rd/rs1/rs2 index rules and the six immediate rules,
#                bound to those field positions (OPR_* constants)
#   uop.py     — one µop template per instruction of the RV32I listing (§6.4)
#   mop.py     — MOP_TABLE, the Mop groups binding encodings to those templates
#   rv32i.py   — the IsaBase assembly
# Not supplied: the trap policy (§6.5), which has no type yet.
#
# The operand rules are module constants, so the register class they target
# is one too: `reg.RegFile`, built by `x_file()` and shared by every shape
# and by the `reg_files=(RegFile,)` the description declares. IsaBase matches reg files by
# IDENTITY, and sharing constants is what makes those the same object.
# Consequence: two rv32i() builds share it — call `x_file()` and build your own
# operands if you need genuinely independent descriptions. MOP_TABLE is shared
# on the same terms and for the same reason; `exec_units()` stays a function.
# Nothing mutates any of it.
#
# Every file carries a KNOWN GAPS block naming what it cannot express. The
# short version: Uop has no immediate, PC is not nameable as a µop input, and
# a matcher discriminates but does not extract — so this package proves the
# SHAPES fit the contract and the container's cross-checks pass, and the table
# now tells its instructions apart, but an immediate still cannot be built
# from it. Those gaps are contract-side; fixing them must not touch uarch.
#
# Rules this package obeys (CLAUDE.md §3): description data only, no hardware
# code, no Kathryn import, and no import from carolyne.uarch.

from __future__ import annotations

from .field_match import ILEN_BYTES
from .operand import (OPR_IMM_B, OPR_IMM_I, OPR_IMM_J, OPR_IMM_S, OPR_IMM_U,
                      OPR_IMM_SHAMT, OPR_IMMS, OPR_RD, OPR_REGS, OPR_RS1,
                      OPR_RS2)
from .mop import MOP_TABLE
from .op import OPS, exec_units
from .reg import ImmTarget, RegFile, X_LEN, x_file
from .rv32i import rv32i
from .uop import UOPS

__all__ = [
    "rv32i", "MOP_TABLE", "OPS", "exec_units", "ILEN_BYTES",
    "RegFile", "ImmTarget", "X_LEN", "x_file",
    "OPR_RD", "OPR_RS1", "OPR_RS2", "OPR_REGS",
    "OPR_IMM_I", "OPR_IMM_S", "OPR_IMM_B", "OPR_IMM_U", "OPR_IMM_J",
    "OPR_IMM_SHAMT", "OPR_IMMS", "UOPS",
]
