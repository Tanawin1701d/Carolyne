# Uop — one µop template of a cracked instruction (uop_contract.md §1.4/§2):
# the operation itself and the operand slots the generated hardware fills at
# runtime. Like every ISA-layer type this is TEMPLATE only — srcs/dests are
# index *rules* (Operand), imm is an extraction rule or a cracker-baked
# constant, never a runtime value.
#
# THE TEMPLATE IS THE KIND. A µop names ITSELF: `name` is what the description
# calls this operation, unique across the ISA, and `uop_idx` is the id the
# hardware plane speaks — the value every record's `uop_idx` field carries,
# DECLARED on the template rather than read off its position in `isa.uops`
# (position is declaration order and nothing more, so reordering the tuple can
# never renumber the hardware). IsaBase holds the declared ids to unique and
# dense 0..N-1, which is what keeps the record field's width honest. An `Op`
# type sat between name and id until 2026-08-23 and was removed: it held a
# name and nothing else, and no record ever carried an op index for a body to
# compare against.
#
# Operand counts are capped at the record's shape (§2: src[0..2], dest[0..1]).
# An instruction family sharing one shape is a factory function in the per-ISA
# package. The template names no unit: which ExecUnit executes it is answered
# by the unit set at elaboration. It carries NO matcher either — picking an
# instruction out of the word is the ENCODING side's job, and Mop/UopSeq
# (mop.py) hold those rules; a template names the operation, never its
# encoding.
# A slot holds an Operand and nothing else, and this is the one place that sees
# both an operand's own role and its position, so it holds them to each other.
# No first/last bound here — that comes from position in the cracker sequence.
# mem (size/sign) and br (cond-kind) sub-fields are deferred until the FU
# semantics that consume them land.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union

from .atomic_operand import DEST_ROLES, SRC_ROLES
from .operand import FieldRef, Operand

ImmRule = Union[int, FieldRef]

# Hardware-plane record shape, uop_contract.md §2.
MAX_SRCS  = 3       # 3rd source: store data / old-flags read
MAX_DESTS = 2       # 2nd dest: flags write (x86), link reg


@dataclass(frozen=True)
class Uop:

    name    : str                       # what this µop IS, e.g. "ADD"
    uop_idx : int                       # the id the hardware plane speaks;
                                        # unique + dense per ISA (IsaBase)
    srcs    : Tuple[Operand, ...] = ()
    dests   : Tuple[Operand, ...] = ()
    # What this µop IS to the machine, beyond its operands: "is_branch",
    # "is_store", ... A REQUEST, the same bargain ExecUnit.needs makes — the
    # ISA states the fact and the generator decides what hardware it means,
    # so no vocabulary ships here and an ISA may name one nobody reads yet.
    specified_feature : Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (isinstance(self.name, str) and self.name):
            raise ValueError(f"Uop needs a non-empty name, got {self.name!r}")
        if isinstance(self.uop_idx, bool) or not isinstance(self.uop_idx, int):
            raise TypeError(
                f"Uop '{self.name}': uop_idx must be an int, "
                f"got {type(self.uop_idx).__name__}")
        if self.uop_idx < 0:
            raise ValueError(
                f"Uop '{self.name}': uop_idx must be >= 0, got {self.uop_idx}")
        object.__setattr__(self, "srcs",  tuple(self.srcs))    # accept any sequence
        object.__setattr__(self, "dests", tuple(self.dests))
        object.__setattr__(self, "specified_feature",
                           tuple(self.specified_feature))
        seen = set()
        for feature in self.specified_feature:
            if not (isinstance(feature, str) and feature):
                raise ValueError(
                    f"Uop '{self.name}': specified_feature holds non-empty "
                    f"strings, got {feature!r}")
            if feature in seen:
                raise ValueError(
                    f"Uop '{self.name}': specified_feature names "
                    f"'{feature}' twice")
            seen.add(feature)
        for kind, roles, operands, limit in (("src",  SRC_ROLES,  self.srcs,  MAX_SRCS),
                                            ("dest", DEST_ROLES, self.dests, MAX_DESTS)):
            if len(operands) > limit:
                raise ValueError(
                    f"Uop '{self.name}': {len(operands)} {kind} operands, "
                    f"record carries at most {limit} (uop_contract.md §2)")
            for slot, operand in enumerate(operands):
                if not isinstance(operand, Operand):
                    raise TypeError(
                        f"Uop '{self.name}': {kind} operands must be Operand, "
                        f"got {type(operand).__name__}")
                if operand.role not in roles:
                    raise ValueError(
                        f"Uop '{self.name}': {kind} slot {slot} holds an operand "
                        f"declared {operand.role} — an operand's role must match "
                        f"the list it sits in")

    def has_feature(self, feature: str) -> bool:
        """This µop declares that feature — the one door a generator reads,
        so no consumer spells `in uop.specified_feature` itself."""
        return feature in self.specified_feature

    def __str__(self) -> str:
        return self.name