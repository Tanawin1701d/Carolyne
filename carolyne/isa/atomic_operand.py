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
# that resolve differently — the shape an ISA needs when a single encoding slot
# is a register in one form and a loaded value in another (x86 ModRM r/m).
#
# Decisions (2026-08-15):
# - This type is the CORE of an operand, not a variant of one. Operand
#   composes it rather than repeating role and targets.
# - OperandRole and TargetKind are declared HERE, with the smaller type, so
#   the dependency runs operand -> atomic_operand and never back.
# - TWO OPTIONAL target fields, not one Union field. A Union says "this slot
#   names exactly one of these, decided here"; the pair says "these are the
#   values this slot may name, and the Operand decides". The second is what
#   lets a core be shared across rules that select differently. Cost, and it
#   is a real one: a core no longer states WHICH value a slot names, only the
#   candidates, so two rules sharing a core share a *menu* — the check that a
#   slot targets what it should now lives on Operand, where the selection is.
# - The core carries NO `width`, NO `is_arch`, NO `is_intermediate`: with two
#   candidate targets each is ambiguous, and only the selection answers them.
#   `has_arch`/`has_temp` say what is on offer; `target_for(kind)` performs the
#   selection, so the one place that knows how a kind maps to a field is here.
# - It carries no is_const and no is_decoded either. Each is a fact about the
#   INDEX, which this type has not got: whether a slot is hardwired depends on
#   WHICH register of the class it names, and whether it is decoded depends on
#   where that index comes from. Answering either here would mean guessing.
# - REMOVED on the way here (don't restore from git): a rule refusing a target
#   with more than one register, which could not survive Operand holding a
#   core — 30 of RV32I's 37 operands target a 32-register file. Its useful half
#   lives on in Operand, which lets the index be OMITTED exactly when the class
#   holds one register.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from .reg import Intermediate, RegFile


# Which direction the slot flows, and therefore which rename port it becomes.
# Values are the words Uop's error messages use, so `f"{role}"` reads right.
#
# This IS an enum where Op (op.py) deliberately is not: the two are different
# kinds of set. An ISA may declare an op nobody anticipated, but contract §2
# gives the record exactly src[0..2] and dest[0..1] slots, so no ISA can
# invent a third role. A closed set is an enum.
#
# There is no SRC_DEST member. An arch slot both read and written through one
# encoding field (x86 `add eax, ebx`) becomes TWO operands, because rename
# genuinely does a RAT read and a RAT write + free-list alloc there, filling
# one src slot AND one dest slot of the record. One object claiming both roles
# would hide two slots behind one entry and force every consumer downstream to
# expand it.
class OperandRole(Enum):
    SRC  = "src"
    DEST = "dest"

    def __str__(self) -> str:
        return self.value


# Which of a core's two targets an operand selects. Closed for the same reason
# OperandRole is: the core has exactly these two slots to choose between.
class TargetKind(Enum):
    ARCH = "arch"       # the core's reg_file — renamed through that class's RAT/PRF
    TEMP = "temp"       # the core's intermediate — the µtemp instance IS the value node

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class AtomicOperand:
    role         : OperandRole              # src or dest; Uop checks it against position
    reg_file     : Optional[RegFile]      = None    # arch class this slot may name
    intermediate : Optional[Intermediate] = None    # µtemp this slot may name

    def __post_init__(self) -> None:
        if not isinstance(self.role, OperandRole):
            raise TypeError(
                f"AtomicOperand role must be an OperandRole, got {type(self.role).__name__} "
                f"(OperandRole.SRC or OperandRole.DEST)")
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
        # The selection itself, so the kind -> field mapping is written once.
        # Raises rather than returning None: a slot selecting a target the core
        # does not offer is a broken rule, not an empty one.
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
    def has_temp(self) -> bool:
        return self.intermediate is not None

    @property
    def is_src(self) -> bool:
        return self.role is OperandRole.SRC

    @property
    def is_dest(self) -> bool:
        return self.role is OperandRole.DEST
