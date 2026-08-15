# Operand — one source or destination slot of a µop template: an AtomicOperand
# (which value, which direction) plus the ENCODING SIDE around it — the index
# rule by which the generated hardware finds the register, and the matcher
# saying where in the instruction word that index is read from.
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
# FieldRef lives here rather than in its own module: it is the index rule of
# an Operand (and the same rule for a Uop's imm), meaningless on its own, and
# a one-field dataclass is not worth a file.
#
# Decisions (2026-08-15):
# - The (target, role) pair is NOT repeated here: Operand HOLDS an
#   AtomicOperand (atomic_operand.py) and forwards `target`/`role` as
#   properties, so there is one definition of what a value-and-direction is
#   and code that needs only that much can take the core alone. Composition,
#   not inheritance — Operand is not substitutable for its core, since it
#   demands an index rule the core knows nothing about.
# - Consequence, accepted: every construction site names the core —
#   `Operand(AtomicOperand(x, DEST), FieldRef("rd"))`. Per-ISA packages keep
#   the noise down by sharing core constants (riscv/operand.py), which is free
#   because an AtomicOperand is frozen and value-equal.
# - The role lives in the core, so an operand still states its own direction
#   and Uop still cross-checks it against srcs/dests position (uop.py). A
#   shared constant self-documents: OPR_RD *is* a destination, in every
#   template that uses it.
# - `index` may now be OMITTED on a one-register class. This is the surviving
#   half of a rule that briefly lived in AtomicOperand ("a target the ISA
#   never has to index"); it belongs here, because it is a statement about the
#   index, and only this type has one. is_const then reads register 0, the
#   only register there is.
# - An Operand will NOT point at its post-rename counterpart when the
#   hardware-plane record type lands. Two reasons, either sufficient: a
#   physical index is a run-time value, which the elaboration plane may not
#   hold; and an Operand is a frozen, value-equal, SHARED constant — OPR_RS1
#   is one object across 37 templates — so there is no per-use slot on it to
#   point from. That map has to run one-way, reading an Operand.
# - A Uop slot is an Operand, full stop — never a bare AtomicOperand and never
#   a union of the two (uop.py). A µop template always states its index rule.

from __future__    import annotations

from dataclasses     import dataclass
from typing          import Optional, Union

from .atomic_operand import AtomicOperand, OperandRole
from .reg            import Intermediate, RegFile
from .field_match    import InstrFieldMatch


# A *rule*, not a value: "the register index arrives at runtime from the
# encoding field of this name" (rd/rs1/modrm_reg/...). The ISA layer is pure
# template; elaboration turns a FieldRef into wiring from the generated
# decoder's field extractor into the rename read/write port.
#
# A FieldRef is only a name here. Which bits the field occupies — and whether
# the name exists at all — is defined by the encoding table and checked when
# a cracker is bound to an encoding (that layer lands later). Equality is by
# name: within one instruction template, "rd" is "rd".
@dataclass(frozen=True)
class FieldRef:
    name : str          # encoding field name, e.g. "rd", "rs1", "modrm_reg"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("FieldRef needs a non-empty field name")


IndexRule = Union[int, FieldRef]


@dataclass(frozen=True)
class Operand:
    atomic : AtomicOperand                  # which value, which direction
    index  : Optional[IndexRule] = None     # RegFile targets; omitted on a 1-reg class
    matcher: Optional[InstrFieldMatch] = None   # position only; an operand tests nothing

    def __post_init__(self) -> None:
        if not isinstance(self.atomic, AtomicOperand):
            raise TypeError(
                f"Operand needs an AtomicOperand core, got {type(self.atomic).__name__} "
                f"(AtomicOperand(target, role))")
        target = self.atomic.target
        if isinstance(target, RegFile):
            if self.index is None:
                # Legal only where there is nothing to choose: one register,
                # index_width 0, and the elaborator wires it.
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

    # --- forwarded from the core ----------------------------------------------
    @property
    def target(self) -> Union[RegFile, Intermediate]:
        return self.atomic.target

    @property
    def role(self) -> OperandRole:
        return self.atomic.role

    @property
    def is_src(self) -> bool:
        return self.atomic.is_src

    @property
    def is_dest(self) -> bool:
        return self.atomic.is_dest

    @property
    def is_arch(self) -> bool:
        return self.atomic.is_arch

    @property
    def is_intermediate(self) -> bool:
        return self.atomic.is_intermediate

    @property
    def width(self) -> int:
        return self.atomic.width

    # --- the encoding side, which only this type has ---------------------------
    @property
    def is_decoded(self) -> bool:
        # Index arrives at runtime from an encoding field (vs implicit/µtemp).
        return isinstance(self.index, FieldRef)

    @property
    def is_const(self) -> bool:
        # Statically-known hardwired reg (implicit int index onto a const reg).
        # A decoded index can still hit x0 at runtime — that check is rename's
        # job, elaborated from RegFile.const_regs; it cannot be known here.
        if not self.is_arch:
            return False
        # An omitted index means the class holds one register, which is 0.
        idx = 0 if self.index is None else self.index
        return isinstance(idx, int) and self.target.is_const(idx)
