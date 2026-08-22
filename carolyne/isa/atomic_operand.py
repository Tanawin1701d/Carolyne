# AtomicOperand — the irreducible core of a µop operand: the VALUE(S) a slot
# may name and the DIRECTION it flows. Every Operand (operand.py) holds one and
# adds the encoding side (which of the core's targets it selects, the index
# rule, the matcher) around it.
#
# A core carries up to two targets, not one:
#
#   reg_file      an architectural register class the slot may name
#   intermediate  an intra-instruction µtemp the slot may name
#
# At least one must be present; both may be. The Operand built on the core
# states WHICH of them it selects (`target_kind`), so one core can serve rules
# that resolve differently (x86 ModRM r/m). The core has no width / is_arch /
# is_const of its own: those are answered by the selection, on Operand.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from .reg import Intermediate, RegFile


# Which direction the slot flows, and therefore which rename port it becomes.
# Values are the words Uop's error messages use, so `f"{role}"` reads right.
# No SRC_DEST member: a slot both read and written (x86 `add eax, ebx`) is TWO
# operands, filling one src slot and one dest slot of the record.
#
# DEST_W_REQ is a destination whose write is REQUIRED — the µop must produce it
# before the instruction can retire, so a reservation station carries a
# `wb_required_<name>` bit for it where a plain DEST carries only its index.
class OperandRole(Enum):
    SRC        = "src"
    DEST       = "dest"
    DEST_W_REQ = "dest_w_req"

    def __str__(self) -> str:
        return self.value

    @property
    def is_src(self) -> bool:
        return self is OperandRole.SRC

    @property
    def is_dest(self) -> bool:
        return self in (OperandRole.DEST, OperandRole.DEST_W_REQ)


# The roles a src slot and a dest slot may hold. Two roles are destinations, so
# every consumer that used to compare against DEST tests membership instead.
SRC_ROLES  = (OperandRole.SRC,)
DEST_ROLES = (OperandRole.DEST, OperandRole.DEST_W_REQ)


# Which of a core's two targets an operand selects.
class TargetKind(Enum):
    ARCH = "arch"       # the core's reg_file — renamed through that class's RAT/PRF
    TEMP = "temp"       # the core's intermediate — the µtemp instance IS the value node

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class AtomicOperand:
    role         : OperandRole              # src or dest; Uop checks it against position
    name         : str                    = ""      # slot name; the stem of every
                                                    # hardware field built for this core
    reg_file     : Optional[RegFile]      = None    # arch class this slot may name
    intermediate : Optional[Intermediate] = None    # µtemp this slot may name

    def __post_init__(self) -> None:
        if not isinstance(self.role, OperandRole):
            raise TypeError(
                f"AtomicOperand role must be an OperandRole, got {type(self.role).__name__} "
                f"({', '.join(r.name for r in OperandRole)})")
        if not isinstance(self.name, str):
            raise TypeError(
                f"AtomicOperand name must be a str, got {type(self.name).__name__}")
        if self.name and not self.name.isidentifier():
            raise ValueError(
                f"AtomicOperand name '{self.name}' is not an identifier — it becomes "
                f"the stem of generated field names (valid_<name>, pr_idx_<name>)")
        if self.reg_file is not None and not isinstance(self.reg_file, RegFile):
            raise TypeError(
                f"AtomicOperand reg_file must be a RegFile, "
                f"got {type(self.reg_file).__name__}")
        if self.intermediate is not None and not isinstance(self.intermediate, Intermediate):
            raise TypeError(
                f"AtomicOperand intermediate must be an Intermediate, "
                f"got {type(self.intermediate).__name__}")
        if self.reg_file is None and self.intermediate is None:
            raise ValueError(
                "AtomicOperand names no value: give it a reg_file, an intermediate, "
                "or both (the Operand then selects which with target_kind)")

    def target_for(self, kind: TargetKind) -> Union[RegFile, Intermediate]:
        # Maps a kind to the field holding it; raises if the core lacks it.
        if not isinstance(kind, TargetKind):
            raise TypeError(
                f"target_kind must be a TargetKind, got {type(kind).__name__} "
                f"(TargetKind.ARCH or TargetKind.TEMP)")
        target = self.reg_file if kind is TargetKind.ARCH else self.intermediate
        if target is None:
            raise ValueError(
                f"AtomicOperand offers no {kind} target: it carries "
                f"{'a reg_file' if self.has_arch else 'an intermediate'} only")
        return target

    @property
    def has_arch(self) -> bool:
        return self.reg_file is not None

    @property
    def has_imm(self) -> bool:
        """The slot may name the core's `intermediate` — which is how an
        immediate reaches a µop (RV32I's ImmTarget)."""
        return self.intermediate is not None

    @property
    def is_src(self) -> bool:
        return self.role.is_src

    @property
    def is_dest(self) -> bool:
        return self.role.is_dest

    @property
    def is_write_required(self) -> bool:
        """A destination the µop must write before the instruction retires."""
        return self.role is OperandRole.DEST_W_REQ
