# MIPS32 description package — release 2, little-endian, user-mode integer
# instructions only (no CP0, no FPU, no traps).
#
# It supplies the deliverables of uop_contract.md §6 that have types today:
#   reg.py         — the register classes: r ($0 const), hi, lo
#   field_match.py — where each encoding field is in the 32-bit word, the
#                    three formats, and the addressing group PC_WIDTH /
#                    PC_ALIGN / ILEN_BYTES / RESET_PC that IsaBase carries
#   operand.py     — the register index rules and the immediate rules
#   imm.py         — what each immediate's matched bits MEAN
#   uop.py         — one µop template per instruction (63)
#   mop.py         — MOP_TABLE, the Mops binding encodings to templates
#   exec_unit.py   — the unit FACTORY; each unit's semantics is in its own
#                    module (exec_unit_alu / _br / _ls / _muldiv)
#   mips32.py      — the IsaBase assembly
# Not supplied: the trap policy (§6.5), which has no type yet.
#
# The same sharing terms as the RISC-V package: the operand rules are module
# constants, so the register classes they target are shared instances
# (GPR_FILE, HI_FILE, LO_FILE), and MOP_TABLE is a constant too; `exec_units()`
# stays a function.
#
# Every branch and jump carries the feature "delay_slot" (uop.py header):
# the engine does not read it yet, so a build holds each slot to a nop.
#
# Rules this package obeys (CLAUDE.md §3): description data only, no Kathryn
# import outside the exec_unit_* semantics modules, and no import from
# carolyne.uarch.

from __future__ import annotations

from .exec_unit import exec_units
from .exec_unit_alu import AluExecUnit
from .exec_unit_br import BrExecUnit
from .exec_unit_ls import LSExecUnit
from .exec_unit_muldiv import MulDivExecUnit
from .field_match import ILEN_BYTES, PC_ALIGN, PC_WIDTH, RESET_PC
from .mips32 import Mips32
from .mop import MOP_TABLE
from .operand import ATOMIC_OPERANDS, OPR_IMMS, OPR_REGS
from .reg import (GPR_FILE, HI_FILE, IMM_TARGET, LO_FILE, X_LEN, build_gpr_file,
                  build_hi_file, build_lo_file)
from .uop import BRANCHES, CONTROL, JUMPS, LINKS, LOADS, MULDIVS, STORES, UOPS

__all__ = [
    "Mips32"         , "MOP_TABLE"    , "exec_units"   ,
    "AluExecUnit"    , "BrExecUnit"   , "LSExecUnit"   , "MulDivExecUnit",
    "PC_WIDTH"       , "PC_ALIGN"     , "ILEN_BYTES"   , "RESET_PC"      ,
    "GPR_FILE"       , "HI_FILE"      , "LO_FILE"      , "IMM_TARGET"    , "X_LEN",
    "build_gpr_file" , "build_hi_file", "build_lo_file",
    "ATOMIC_OPERANDS", "OPR_REGS"     , "OPR_IMMS"     ,
    "UOPS"           , "LOADS"        , "STORES"       , "BRANCHES"      , "JUMPS", "LINKS", "CONTROL", "MULDIVS",
]
