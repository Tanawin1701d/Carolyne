# Uop — one µop template of a cracked instruction (uop_contract.md §1.4/§2):
# which operation runs and the operand slots the generated hardware fills at
# runtime. Like every ISA-layer type this is TEMPLATE only — srcs/dests are
# index *rules* (Operand), imm is an extraction rule or a cracker-baked
# constant, never a runtime value.
#
# Operand counts are capped at the record's shape (§2: src[0..2], dest[0..1]).
# `op` is a single concrete Op object — an instruction family sharing one shape
# is a factory function in the per-ISA package. The template names no unit:
# which ExecUnit executes a kind is answered by the unit set at elaboration.
# A slot holds an Operand and nothing else, and this is the one place that sees
# both an operand's own role and its position, so it holds them to each other.
# No first/last bound here — that comes from position in the cracker sequence.
# mem (size/sign) and br (cond-kind) sub-fields are deferred until the FU
# semantics that consume them land.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union

from .atomic_operand import DEST_ROLES, SRC_ROLES
from .field_match import InstrFieldMatch, InstrValueMatch, check_matcher_pair
from .op import Op
from .operand import FieldRef, Operand

ImmRule = Union[int, FieldRef]

# Hardware-plane record shape, uop_contract.md §2.
MAX_SRCS  = 3       # 3rd source: store data / old-flags read
MAX_DESTS = 2       # 2nd dest: flags write (x86), link reg


@dataclass(frozen=True)
class Uop:

    op      : Op
    srcs    : Tuple[Operand, ...] = ()
    dests   : Tuple[Operand, ...] = ()
    matcher_field : Optional[InstrFieldMatch] = None  # which bits pick this template
    matcher_value : Optional[InstrValueMatch] = None  # what they must equal, per segment

    def __post_init__(self) -> None:
        if not isinstance(self.op, Op):
            raise TypeError(
                f"Uop op must be an Op, got {type(self.op).__name__} "
                f"(name it from the catalog, or <unit>.op(<name>))")
        object.__setattr__(self, "srcs",  tuple(self.srcs))    # accept any sequence
        object.__setattr__(self, "dests", tuple(self.dests))
        for kind, roles, operands, limit in (("src",  SRC_ROLES,  self.srcs,  MAX_SRCS),
                                            ("dest", DEST_ROLES, self.dests, MAX_DESTS)):
            if len(operands) > limit:
                raise ValueError(
                    f"Uop '{self.op}': {len(operands)} {kind} operands, "
                    f"record carries at most {limit} (uop_contract.md §2)")
            for slot, operand in enumerate(operands):
                if not isinstance(operand, Operand):
                    raise TypeError(
                        f"Uop '{self.op}': {kind} operands must be Operand, "
                        f"got {type(operand).__name__}")
                if operand.role not in roles:
                    raise ValueError(
                        f"Uop '{self.op}': {kind} slot {slot} holds an operand "
                        f"declared {operand.role} — an operand's role must match "
                        f"the list it sits in")
        check_matcher_pair(self.matcher_field, self.matcher_value,
                           where=f"Uop '{self.op}'")