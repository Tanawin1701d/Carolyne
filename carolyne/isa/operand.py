# Operand — one source or destination slot of a µop template. It links to
# either an architectural register file or an Intermediate µtemp.
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
#
# An Intermediate target needs no index: the instance IS the value node.
#
# FieldRef lives here rather than in its own module: it is the index rule of
# an Operand (and the same rule for a Uop's imm), meaningless on its own, and
# a one-field dataclass is not worth a file.

from __future__    import annotations

from dataclasses   import dataclass
from typing        import Optional, Union

from .reg          import Intermediate, RegFile
from .field_match  import InstrFieldMatch


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
    target : Union[RegFile, Intermediate]
    index  : Optional[IndexRule] = None     # RegFile targets only
    matcher: Optional[InstrFieldMatch] = None

    def __post_init__(self) -> None:
        if isinstance(self.target, RegFile):
            if self.index is None:
                raise ValueError(
                    f"Operand on reg file '{self.target.name}' needs an index rule "
                    f"(FieldRef for a decoded register, int for an implicit one)")
            if isinstance(self.index, int):
                if not (0 <= self.index < self.target.amount):
                    raise ValueError(
                        f"Operand index {self.index} out of range 0..{self.target.amount - 1} "
                        f"for reg file '{self.target.name}'")
            elif not isinstance(self.index, FieldRef):
                raise TypeError(
                    f"Operand index must be an int or FieldRef, got {type(self.index).__name__}")
        elif isinstance(self.target, Intermediate):
            if self.index is not None:
                raise ValueError("Operand on an Intermediate carries no index")
        else:
            raise TypeError(
                f"Operand target must be a RegFile or Intermediate, got {type(self.target).__name__}")

    @property
    def is_arch(self) -> bool:
        return isinstance(self.target, RegFile)

    @property
    def is_intermediate(self) -> bool:
        return isinstance(self.target, Intermediate)

    @property
    def is_decoded(self) -> bool:
        # Index arrives at runtime from an encoding field (vs implicit/µtemp).
        return isinstance(self.index, FieldRef)

    @property
    def width(self) -> int:
        # Both target kinds carry their own width — the operand just exposes it.
        return self.target.width

    @property
    def is_const(self) -> bool:
        # Statically-known hardwired reg (implicit int index onto a const reg).
        # A decoded index can still hit x0 at runtime — that check is rename's
        # job, elaborated from RegFile.const_regs; it cannot be known here.
        return self.is_arch and isinstance(self.index, int) and self.target.is_const(self.index)
