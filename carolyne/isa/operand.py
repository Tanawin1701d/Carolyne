# Operand — one source or destination slot of a µop template: an AtomicOperand
# (the values on offer and the direction) plus the ENCODING SIDE around it —
# WHICH of the core's targets this slot names, the index rule by which the
# generated hardware finds the register, and the matcher saying where in the
# instruction word that index is read from.
#
# The ISA layer is a TEMPLATE: an operand never holds a runtime value, only
# the rule the generated hardware uses to find the register at runtime.
# For a RegFile target the index is one of:
#
#   FieldRef("rd")  runtime-decoded — elaborates to wiring from the decoder's
#                   field extractor into the rename port (the normal case)
#   int             implicit fixed register — part of the ISA itself (x86
#                   push/pop use ESP, flags writes hit the one flags reg);
#                   elaborates to a constant wire into the same rename port
#   omitted         only when the class holds ONE register: index_width is 0,
#                   so there is nothing to choose and the elaborator wires the
#                   single register (x86 FLAGS)
#
# An Intermediate target needs no index either: the instance IS the value node.
#
# Operand HOLDS an AtomicOperand rather than extending it. `target_kind` is the
# selector, required and resolved in __post_init__, so a rule selecting a
# target its core does not carry fails at construction. The selection lives
# here, so `target`, `width`, `is_arch` and `is_intermediate` do too; only
# `role`/`is_src`/`is_dest` forward from the core.
#
# FieldRef lives here rather than in its own module: it is the index rule of
# an Operand (and the same rule for a Uop's imm), meaningless on its own.

from __future__    import annotations

from dataclasses     import dataclass
from typing          import Optional, Union

from .atomic_operand import AtomicOperand, OperandRole, TargetKind
from .reg            import Intermediate, RegFile
from .field_match    import InstrFieldMatch


# A *rule*, not a value: "the register index arrives at runtime from the
# encoding field of this name" (rd/rs1/modrm_reg/...). The ISA layer is pure
# template; elaboration turns a FieldRef into wiring from the generated
# decoder's field extractor into the rename read/write port.
#
# A FieldRef is only a name here; which bits the field occupies is defined by
# the encoding table. Equality is by name.
@dataclass(frozen=True)
class FieldRef:
    name : str          # encoding field name, e.g. "rd", "rs1", "modrm_reg"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("FieldRef needs a non-empty field name")


IndexRule = Union[int, FieldRef]


@dataclass(frozen=True)
class Operand:
    atomic     : AtomicOperand                  # which values are on offer, which direction
    target_kind: TargetKind                     # WHICH of the core's targets this slot names
    index      : Optional[IndexRule] = None     # RegFile targets; omitted on a 1-reg class
    matcher    : Optional[InstrFieldMatch] = None   # position only; an operand tests nothing

    def __post_init__(self) -> None:
        if not isinstance(self.atomic, AtomicOperand):
            raise TypeError(
                f"Operand needs an AtomicOperand core, got {type(self.atomic).__name__} "
                f"(AtomicOperand(role, reg_file=..., intermediate=...))")
        # Raises if the core does not offer this kind.
        target = self.atomic.target_for(self.target_kind)
        if isinstance(target, RegFile):
            if self.index is None:
                # Legal only on a one-register class: index_width is 0.
                if target.amount != 1:
                    raise ValueError(
                        f"Operand on reg file '{target.name}' needs an index rule "
                        f"(FieldRef for a decoded register, int for an implicit one); "
                        f"it may be omitted only on a one-register class, and this one "
                        f"holds {target.amount}")
            elif isinstance(self.index, int):
                if not (0 <= self.index < target.amount):
                    raise ValueError(
                        f"Operand index {self.index} out of range 0..{target.amount - 1} "
                        f"for reg file '{target.name}'")
            elif not isinstance(self.index, FieldRef):
                raise TypeError(
                    f"Operand index must be an int or FieldRef, got {type(self.index).__name__}")
        elif self.index is not None:
            raise ValueError("Operand on an Intermediate carries no index")

    # --- the selection: which of the core's targets this slot names -----------
    @property
    def target(self) -> Union[RegFile, Intermediate]:
        return self.atomic.target_for(self.target_kind)

    @property
    def is_arch(self) -> bool:
        return self.target_kind is TargetKind.ARCH

    @property
    def is_intermediate(self) -> bool:
        return self.target_kind is TargetKind.TEMP

    @property
    def width(self) -> int:
        # The SELECTED target's width.
        return self.target.width

    # --- forwarded from the core ----------------------------------------------
    @property
    def role(self) -> OperandRole:
        return self.atomic.role

    @property
    def is_src(self) -> bool:
        return self.atomic.is_src

    @property
    def is_dest(self) -> bool:
        return self.atomic.is_dest

    # --- the encoding side, which only this type has ---------------------------
    @property
    def is_decoded(self) -> bool:
        # Index arrives at runtime from an encoding field (vs implicit/µtemp).
        return isinstance(self.index, FieldRef)

    @property
    def is_const(self) -> bool:
        # Statically-known hardwired reg (implicit int index onto a const reg).
        # A decoded index hitting x0 is rename's runtime check, not this one.
        if not self.is_arch:
            return False
        # An omitted index means the class holds one register, which is 0.
        idx = 0 if self.index is None else self.index
        return isinstance(idx, int) and self.target.is_const(idx)
