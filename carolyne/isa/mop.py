# Mop / UopSeq — the encoding side: a macro-op is one encoding group, and each
# UopSeq variant binds a finer field match to the µop sequence it decodes to.
#
# Decision (2026-08-14): InstrFieldMatch used to live here, which made this
# module a dependency of Operand and Uop and forced the `Uop` annotation below
# to be a stringified TYPE_CHECKING import to dodge the cycle. It now lives in
# field_match.py and the dependency runs one way: field_match → operand/uop →
# mop, so Uop is a plain import.
#
# Decision (2026-08-15): the matcher is TWO slots, `matcher_field` (which bits)
# and `matcher_value` (what they must equal), not one slot typed as either.
# Two slots is what makes the pair checkable — check_matcher_pair holds them to
# each other, which neither type can do alone — and "positions only, nothing
# tested yet" is then just matcher_value left None, the state RV32I is in.
# Mop requires its matcher_field; every value slot defaults to None.

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple

from .field_match import InstrFieldMatch, InstrValueMatch, check_matcher_pair
from .uop import Uop


@dataclass(frozen=True)
class UopSeq:
    uops          : Tuple[Uop, ...] = ()
    matcher_field : Optional[InstrFieldMatch] = None  # which bits pick this variant
    matcher_value : Optional[InstrValueMatch] = None  # what they must equal, per segment

    def __post_init__(self):
        if len(self.uops) == 0:
            raise IndexError("uop sequence must have at least one uop")

        check_matcher_pair(self.matcher_field, self.matcher_value, where="UopSeq")


@dataclass(frozen=True)
class Mop:
    matcher_field : Optional[InstrFieldMatch] = None  # which bits pick this group
    matcher_value : Optional[InstrValueMatch] = None  # what they must equal, per segment
    uop_seq       : Tuple[UopSeq, ...] = ()

    def __post_init__(self):
        if len(self.uop_seq) == 0:
            raise IndexError("Mop must have at least one uop")

        if self.matcher_field is None:
            raise IndexError("Mop must have a matcher_field")

        check_matcher_pair(self.matcher_field, self.matcher_value, where="Mop")

