# AtomicOperand — the irreducible core of a µop operand: WHICH value and in
# WHICH direction, and nothing else. Every Operand (operand.py) holds one and
# adds the encoding side (index rule, matcher) around it.
#
# The value is either an architectural register class (RegFile) or an
# intra-instruction µtemp (Intermediate); the direction is src or dest, which
# is also the rename port the slot becomes — SRC a RAT read, DEST a RAT write
# plus a free-list allocation.
#
# Decisions (2026-08-15):
# - This type is the CORE of an operand, not a variant of one. Operand
#   composes it rather than repeating (target, role), so there is exactly one
#   place that says what a value-and-direction is, and code that needs only
#   that much can hold an AtomicOperand without dragging an index rule it has
#   no use for.
# - OperandRole is declared HERE, with the smaller type, so the dependency
#   runs operand -> atomic_operand and never back.
# - It carries NO is_const and NO is_decoded, though Operand has both. Each is
#   a fact about the INDEX, which this type does not have: whether a slot is
#   hardwired depends on WHICH register of the class it names, and whether it
#   is decoded depends on where that index comes from. Answering either here
#   would mean guessing.
# - REMOVED the same day it was written: an earlier version refused a target
#   with more than one register, meaning "a slot the ISA never has to index"
#   (µtemp, or a one-register class like x86 FLAGS). That rule cannot survive
#   Operand holding one of these — 30 of RV32I's 37 operands target a
#   32-register file — so it is gone; don't restore it from git. The useful
#   half of it moved to Operand, which now lets the index be OMITTED exactly
#   when the class holds one register.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Union

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


@dataclass(frozen=True)
class AtomicOperand:
    target : Union[RegFile, Intermediate]
    role   : OperandRole                    # src or dest; Uop checks it against position

    def __post_init__(self) -> None:
        if not isinstance(self.role, OperandRole):
            raise TypeError(
                f"AtomicOperand role must be an OperandRole, got {type(self.role).__name__} "
                f"(OperandRole.SRC or OperandRole.DEST)")
        if not isinstance(self.target, (RegFile, Intermediate)):
            raise TypeError(
                f"AtomicOperand target must be a RegFile or Intermediate, "
                f"got {type(self.target).__name__}")

    @property
    def is_src(self) -> bool:
        return self.role is OperandRole.SRC

    @property
    def is_dest(self) -> bool:
        return self.role is OperandRole.DEST

    @property
    def is_arch(self) -> bool:
        return isinstance(self.target, RegFile)

    @property
    def is_intermediate(self) -> bool:
        return isinstance(self.target, Intermediate)

    @property
    def width(self) -> int:
        # Both target kinds carry their own width — the operand just exposes it.
        return self.target.width
