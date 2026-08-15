# The RV32I assembly: the IsaBase that ties the four vocabularies together
# (uop_contract.md §6). The instruction table itself moved to mop.py on
# 2026-08-15 — this file is now the handoff point and nothing else.
#
# Decisions (2026-08-14):
# - `rv32i()` is a factory returning IsaBase, not an IsaBase subclass: RV32I
#   has no description fields the container does not already model, and a
#   factory keeps every ISA the same type downstream (isa.py header).
# - The shapes name the shared operand constants of operand.py, which target
#   the shared register class reg.RegFile — and `rv32i()` declares that same
#   instance. IsaBase matches reg files by identity, so those two must be one
#   object; sharing module constants is what makes that true by construction
#   (and is why nothing here takes a register-class argument).
#
# Decision (2026-08-15): the four cores, the nine operand rules and the 40 µop
# templates are declared here alongside the mops, from the same module
# constants the shapes are built out of. IsaBase matches all three by identity
# for the same reason it matches reg files that way, so listing the constants
# — not rebuilt copies of them — is what makes the cross-check pass, and what
# makes it mean something.
#
# Decision (2026-08-15): `mops=MOP_TABLE` is a constant, not a `mop_table()`
# call. The whole table is frozen data, so every build handing out the same
# tuple changes nothing observable — and it is the same object-sharing bargain
# reg.RegFile already makes (mop.py header).
#
# The KNOWN GAPS of the description live with the parts that carry them:
# mop.py for the encoding table, uop.py for the µop shapes, field_match.py for
# the field positions. Nothing about the assembly below is blocked on them.

from __future__ import annotations

from ..isa import IsaBase
from .mop import MOP_TABLE
from .op import OPS, exec_units
from .operand import (AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3,
                      OPR_IMMS, OPR_REGS)
from .reg import RegFile
from .uop import UOPS


def rv32i() -> IsaBase:
    """The RV32I description — the object a generator is handed."""
    return IsaBase(name="rv32i",
                   reg_files=(RegFile,),  # the instance operand.py's rules target
                   atomic_operands=(AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3, AOPR_DEST_1),
                   operands=OPR_REGS + OPR_IMMS,
                   ops=OPS,
                   exec_units=exec_units(),
                   uops=UOPS,
                   mops=MOP_TABLE)
