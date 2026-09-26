# The MIPS32 assembly: the IsaBase that ties the vocabularies together
# (uop_contract.md §6). The instruction table itself is in mop.py; this file
# only collects the parts.
#
# `Mips32` is a SUBCLASS of IsaBase supplying every vocabulary as a field
# DEFAULT, so `Mips32()` is the whole description and `Mips32(name=...)`
# varies one part of it. It stays DATA — field defaults only, no override of
# __post_init__ / uop() / units_for() — so every inherited cross-check runs.
# Every field is redeclared because a dataclass picks up a default only
# through an ANNOTATED assignment.
#
# The shapes name the shared constants of operand.py / uop.py / mop.py, and
# this file declares those same instances: IsaBase matches cores, operands,
# µops and reg files by IDENTITY.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ..atomic_operand import AtomicOperand
from ..exec_unit import ExecUnit
from ..isa import IsaBase
from ..mop import Mop
from ..operand import Operand
from ..reg import RegFile
from ..uop import Uop
from .exec_unit import exec_units
from .field_match import DLEN_BYTES, ILEN_BYTES, PC_ALIGN, PC_WIDTH, RESET_PC
from .mop import MOP_TABLE
from .operand import ATOMIC_OPERANDS, OPR_IMMS, OPR_REGS
from .reg import GPR_FILE, HI_FILE, LO_FILE
from .uop import UOPS

# Built once, at import: a field default is evaluated once, and every Mips32()
# sharing one unit tuple changes nothing (units are matched by name).
EXEC_UNITS = exec_units()


@dataclass(frozen=True)
class Mips32(IsaBase):
    """The MIPS32 description — the object a generator is handed."""

    name            : str                       = "mips32"
    pc_width        : int                       = PC_WIDTH
    pc_align        : int                       = PC_ALIGN
    ilen_bytes      : int                       = ILEN_BYTES
    dlen_bytes      : int                       = DLEN_BYTES
    reset_pc        : int                       = RESET_PC
    reg_files       : Tuple[RegFile, ...]       = (GPR_FILE, HI_FILE, LO_FILE)
    atomic_operands : Tuple[AtomicOperand, ...] = ATOMIC_OPERANDS
    operands        : Tuple[Operand, ...]       = OPR_REGS + OPR_IMMS
    exec_units      : Tuple[ExecUnit, ...]      = EXEC_UNITS
    uops            : Tuple[Uop, ...]           = UOPS
    mops            : Tuple[Mop, ...]           = MOP_TABLE
