# The RV32I assembly: the IsaBase that ties the vocabularies together
# (uop_contract.md §6). The instruction table itself moved to mop.py on
# 2026-08-15 — this file is now the handoff point and nothing else.
#
# `Rv32i` is a SUBCLASS of IsaBase supplying every vocabulary as a field
# DEFAULT, so `Rv32i()` is the whole description and `Rv32i(name=...)` varies
# one part of it. It stays DATA — field defaults only, no override of
# __post_init__ / uop() / units_for() — so every inherited cross-check still
# runs. All ten fields are redeclared because a dataclass picks up a default
# only through an ANNOTATED assignment; that is why the RegFile CLASS and this
# ISA's one RegFile INSTANCE both appear below, the latter aliased X_FILE.
#
# The shapes name the shared constants of operand.py / uop.py / mop.py, and
# this file declares those same instances: IsaBase matches cores, operands,
# µops and reg files by IDENTITY, so listing the constants rather than rebuilt
# copies is what makes the cross-check pass and mean something.
#
# The three addressing scalars are named from field_match.py, not written as
# literals here, so they stay beside the field positions they belong with.
#
# The KNOWN GAPS of the description live with the parts that carry them:
# mop.py for the encoding table, uop.py for the µop shapes, field_match.py for
# the field positions. Nothing about the assembly below is blocked on them.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ..atomic_operand import AtomicOperand
from ..exec_unit import ExecUnit
from ..isa import IsaBase
from ..mop import Mop
from ..operand import Operand
from ..reg import RegFile                 # the CLASS, for the field annotations
from ..uop import Uop
from .field_match import ILEN_BYTES, PC_ALIGN, PC_WIDTH
from .mop import MOP_TABLE
from .exec_unit import exec_units
from .operand import (AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3,
                      OPR_IMMS, OPR_REGS)
from .reg import RegFile as X_FILE        # the INSTANCE operand.py's rules target
from .uop import UOPS

# Built once, at import: a field default is evaluated once, and every Rv32i()
# sharing one unit tuple changes nothing (units are matched by name).
EXEC_UNITS = exec_units()


@dataclass(frozen=True)
class Rv32i(IsaBase):
    """The RV32I description — the object a generator is handed."""

    name            : str                       = "rv32i"
    pc_width        : int                       = PC_WIDTH
    pc_align        : int                       = PC_ALIGN
    ilen_bytes      : int                       = ILEN_BYTES
    reg_files       : Tuple[RegFile, ...]       = (X_FILE,)
    atomic_operands : Tuple[AtomicOperand, ...] = (AOPR_SRC_1, AOPR_SRC_2,
                                                   AOPR_SRC_3, AOPR_DEST_1)
    operands        : Tuple[Operand, ...]       = OPR_REGS + OPR_IMMS
    exec_units      : Tuple[ExecUnit, ...]      = EXEC_UNITS
    uops            : Tuple[Uop, ...]           = UOPS
    mops            : Tuple[Mop, ...]           = MOP_TABLE
