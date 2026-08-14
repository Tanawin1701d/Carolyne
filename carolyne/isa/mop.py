# Mop / UopSeq — the encoding side: a macro-op is one encoding group, and each
# UopSeq variant binds a finer field match to the µop sequence it decodes to.
#
# Decision (2026-08-14): InstrFieldMatch used to live here, which made this
# module a dependency of Operand and Uop and forced the `Uop` annotation below
# to be a stringified TYPE_CHECKING import to dodge the cycle. It now lives in
# field_match.py and the dependency runs one way: field_match → operand/uop →
# mop, so Uop is a plain import.

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple

from .field_match import InstrFieldMatch
from .uop import Uop


@dataclass(frozen=True)
class UopSeq:
    uops    : Tuple[Uop, ...] = ()
    matcher : Optional[InstrFieldMatch] = None   # one match rule, not a set of them

    def __post_init__(self):
        if len(self.uops) == 0:
            raise IndexError("uop sequence must have at least one uop")


@dataclass(frozen=True)
class Mop:
    matcher : Optional[InstrFieldMatch] = None  # preliminary matcher, one rule
    uop_seq : Tuple[UopSeq, ...] = ()

    def __post_init__(self):
        if len(self.uop_seq) == 0:
            raise IndexError("Mop must have at least one uop")

        if self.matcher is None:
            raise IndexError("Mop must have a matcher")

