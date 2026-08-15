# The RV32I assembly: the IsaBase that ties the vocabularies together
# (uop_contract.md §6). The instruction table itself moved to mop.py on
# 2026-08-15 — this file is now the handoff point and nothing else.
#
# Decisions (2026-08-14):
# - The shapes name the shared operand constants of operand.py, which target
#   the shared register class reg.RegFile — and this file declares that same
#   instance. IsaBase matches reg files by identity, so those two must be one
#   object; sharing module constants is what makes that true by construction
#   (and is why nothing here takes a register-class argument).
#
# Decisions (2026-08-15):
# - The four cores, the nine operand rules and the 40 µop templates are
#   declared here alongside the mops, from the same module constants the shapes
#   are built out of. IsaBase matches all three by identity for the same reason
#   it matches reg files that way, so listing the constants — not rebuilt
#   copies of them — is what makes the cross-check pass, and what makes it mean
#   something. Same for `mops=MOP_TABLE`: frozen data, so every build handing
#   out the same tuple changes nothing observable (mop.py header).
# - `Rv32i` is a SUBCLASS of IsaBase, not a factory function returning one. It
#   supplies every vocabulary as a field DEFAULT, so `Rv32i()` is the whole
#   description and `Rv32i(name="rv32i-dbg")` varies one part of it without a
#   builder signature to thread the rest through. It replaces an `rv32i()`
#   factory that stood here until today; don't restore that from git.
# - It stays DATA, which is what isa.py demands of a subclass: field defaults
#   only, no override of __post_init__/op()/units_for(). Every inherited
#   cross-check still runs at construction, and code holding an IsaBase is
#   holding exactly what it thinks it is.
# - All eight fields are redeclared, and that is not repetition for its own
#   sake: a dataclass picks up a default only through an ANNOTATED assignment,
#   so a bare `name = "rv32i"` would be a plain class attribute and `Rv32i()`
#   would still demand the argument. The base's types are imported for those
#   annotations — which is why the RegFile CLASS and this ISA's one RegFile
#   INSTANCE both appear below, the latter aliased X_FILE to keep them apart.
# - `EXEC_UNITS = exec_units()` is called ONCE, at import, because a field
#   default is evaluated once. Every Rv32i() then shares one unit tuple, where
#   the old factory built fresh units per call. Nothing observable changes:
#   ExecUnit is frozen data and IsaBase matches units by NAME, not identity —
#   the same object-sharing bargain reg.RegFile and MOP_TABLE already make.
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
from ..op import Op
from ..operand import Operand
from ..reg import RegFile                 # the CLASS, for the field annotations
from ..uop import Uop
from .mop import MOP_TABLE
from .op import OPS, exec_units
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
    reg_files       : Tuple[RegFile, ...]       = (X_FILE,)
    atomic_operands : Tuple[AtomicOperand, ...] = (AOPR_SRC_1, AOPR_SRC_2,
                                                   AOPR_SRC_3, AOPR_DEST_1)
    operands        : Tuple[Operand, ...]       = OPR_REGS + OPR_IMMS
    ops             : Tuple[Op, ...]            = OPS
    exec_units      : Tuple[ExecUnit, ...]      = EXEC_UNITS
    uops            : Tuple[Uop, ...]           = UOPS
    mops            : Tuple[Mop, ...]           = MOP_TABLE
