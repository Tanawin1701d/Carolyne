# RV32I description package — a TEMPLATE skeleton, not a finished ISA.
#
# It supplies the deliverables of uop_contract.md §6 that have types today:
#   reg.py       — architectural register classes (§6.1); x only, PC is not one
#   exec_unit.py — the unit FACTORY (exec_units()); each unit's semantics is in
#                  its own module: exec_unit_alu.py / exec_unit_br.py /
#                  exec_unit_ls.py, with shared helpers in exec_unit_util.py
#   field_match.py — where each encoding field is in the 32-bit word (§6.2),
#                  the six base formats as unions of those fields, and the
#                  addressing group PC_WIDTH / PC_ALIGN / ILEN_BYTES that
#                  IsaBase carries (§6.3)
#   operand.py   — the rd/rs1/rs2 index rules and the six immediate rules,
#                  bound to those field positions (OPR_* constants)
#   imm.py       — what each immediate's matched bits MEAN: placement and sign
#   uop.py       — one µop template per instruction of the listing (§6.4)
#   mop.py       — MOP_TABLE, the Mop groups binding encodings to templates
#   rv32i.py     — the IsaBase assembly
# Not supplied: the trap policy (§6.5), which has no type yet.
#
# The operand rules are module constants, so the register class they target is
# one too: `reg.RegFile`, built by `x_file()` and shared by every shape and by
# the `reg_files=(RegFile,)` the description declares, because IsaBase matches
# reg files by IDENTITY. Two Rv32i() builds therefore share it; call `x_file()`
# and build your own operands for a genuinely independent description.
# MOP_TABLE is shared on the same terms; `exec_units()` stays a function.
#
# LIMIT: `Uop` has no immediate field, so the immediates are operands in
# `srcs`, which contract §2 says they should not be (uop.py header). That gap
# is contract-side; fixing it must not touch uarch.
#
# Rules this package obeys (CLAUDE.md §3): description data only, no hardware
# code, no Kathryn import, and no import from carolyne.uarch.

from __future__ import annotations

from .exec_unit_alu import AluExecUnit
from .exec_unit_br import BrExecUnit
from .exec_unit import exec_units
from .exec_unit_ls import LSExecUnit
from .field_match import ILEN_BYTES, PC_ALIGN, PC_WIDTH
from .operand import (OPR_IMM_B, OPR_IMM_I, OPR_IMM_J, OPR_IMM_S, OPR_IMM_U,
                      OPR_IMM_SHAMT, OPR_IMMS, OPR_RD, OPR_REGS, OPR_RS1,
                      OPR_RS2)
from .mop import MOP_TABLE
from .reg import ImmTarget, RegFile, X_LEN, x_file
from .rv32i import Rv32i
from .uop import BRANCHES, LOADS, STORES, UOPS

__all__ = [
    "Rv32i", "MOP_TABLE", "exec_units",
    "AluExecUnit", "BrExecUnit", "LSExecUnit",
    "PC_WIDTH", "PC_ALIGN", "ILEN_BYTES",
    "RegFile", "ImmTarget", "X_LEN", "x_file",
    "OPR_RD", "OPR_RS1", "OPR_RS2", "OPR_REGS",
    "OPR_IMM_I", "OPR_IMM_S", "OPR_IMM_B", "OPR_IMM_U", "OPR_IMM_J",
    "OPR_IMM_SHAMT", "OPR_IMMS", "UOPS", "LOADS", "STORES", "BRANCHES",
]
