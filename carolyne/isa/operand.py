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
#
# Decisions (2026-08-15):
# - An operand states its own ROLE (src or dest). The information also exists
#   positionally, in Uop.srcs vs Uop.dests, so the two could disagree; Uop
#   cross-checks them (uop.py) and that is the price of letting an operand
#   handed around on its own — to a rename-port list, to whatever builds the
#   hardware-plane record slot — still say which direction it is. A shared
#   constant then self-documents: OPR_RD *is* a destination, in every template
#   that uses it.
# - OperandRole IS an enum, unlike Op (op.py deliberately is not). The two
#   are different kinds of set: an ISA may declare an op nobody anticipated,
#   but contract §2 gives the record exactly src[0..2] and dest[0..1] slots,
#   so no ISA can invent a third role. A closed set is an enum.
# - No SRC_DEST member. An arch slot both read and written through one
#   encoding field (x86 `add eax, ebx`) becomes TWO Operand constants, because
#   rename genuinely does a RAT read and a RAT write + free-list alloc there,
#   filling one src slot AND one dest slot of the record. One object claiming
#   both roles would hide two slots behind one entry and force every consumer
#   downstream to expand it.
# - An Operand will NOT point at its post-rename counterpart when the
#   hardware-plane record type lands. Two reasons, either sufficient: a
#   physical index is a run-time value, which the elaboration plane may not
#   hold; and an Operand is a frozen, value-equal, SHARED constant — OPR_RS1
#   is one object across 37 templates — so there is no per-use slot on it to
#   point from. That map has to run one-way, reading an Operand.

from __future__    import annotations

from dataclasses   import dataclass
from enum          import Enum
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


# Which direction the slot flows, and therefore which rename port it becomes:
# SRC -> a RAT read, DEST -> a RAT write plus a free-list allocation. Values
# are the words the Uop error messages already used, so `f"{role}"` reads the
# same as before.
class OperandRole(Enum):
    SRC  = "src"
    DEST = "dest"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Operand:
    target : Union[RegFile, Intermediate]
    role   : OperandRole                    # src or dest; Uop checks it against position
    index  : Optional[IndexRule] = None     # RegFile targets only
    matcher: Optional[InstrFieldMatch] = None   # position only; an operand tests nothing

    def __post_init__(self) -> None:
        if not isinstance(self.role, OperandRole):
            raise TypeError(
                f"Operand role must be an OperandRole, got {type(self.role).__name__} "
                f"(OperandRole.SRC or OperandRole.DEST)")
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
