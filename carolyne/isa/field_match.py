# InstrFieldMatch — where a named encoding field lives in the instruction
# word (uop_contract.md §1.3). One rule, one field: a name plus the bit
# segments it occupies, `(start, end)` with end EXCLUSIVE and bit 0 = LSB.
# InstrValueMatch is the other half — the values those bits must EQUAL, which
# is what makes an encoding discriminable. It names no field: the two are
# separate rules, paired by whoever holds both.
#
# A field is a TUPLE of segments, because it need not be contiguous (RISC-V's
# s/b/j immediates, x86 fields split by prefixes). A value rule states ONE
# VALUE PER SEGMENT, in the same order, so add vs sub reads like the spec
# table: (funct3, funct7). Neither half can check the pairing, so the holder
# of both — Uop, UopSeq, Mop — calls check_matcher_pair at the bottom of this
# file. There is no matches(word) method: evaluating a rule is runtime, and
# this layer holds rules only.
#
# KNOWN GAPS — contract-side, and still blocking decoder generation:
# - No segment placement. For RISC-V's imm_s, (7,12) is imm[4:0] and (25,32)
#   is imm[11:5]; the type records the segments but not where each lands in
#   the assembled value, nor whether the result is sign-extended.
# - Nothing REQUIRES a value: matcher_value defaults to None at every holder,
#   so an encoding stating only field positions is still accepted. Enforcing
#   values for a decodable ISA belongs in IsaBase, which sees the whole table.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class InstrFieldMatch:
    name      : str
    # ORDER IS SIGNIFICANT — nothing here sorts, merges or dedups the segments;
    # consumers read them in the order written (imm_b: (7,8) is imm[11],
    # (8,12) is imm[4:1]).
    match_idx : Tuple[Tuple[int, int], ...]  # ((start_match_idx, end_match_idx), ...), end exclusive

    def __post_init__(self):
        if len(self.match_idx) == 0:
            raise IndexError("InstrFieldMatch must has at least one (start_match_idx, end_match_idx)")
        for seg in self.match_idx:  # a bare (start, end) pair trips this, not the unpack below
            if not isinstance(seg, tuple) or len(seg) != 2:
                raise IndexError(
                    f"InstrFieldMatch match_idx must be a tuple of (start_match_idx, end_match_idx), got {seg!r}")
            start_match_idx, end_match_idx = seg
            if start_match_idx >= end_match_idx:
                raise IndexError("InstrFieldMatch must has start_match_idx < end_match_idx")

    def union(self, *others: "InstrFieldMatch", name: str = "") -> "InstrFieldMatch":

        fields = (self,) + others
        for other in others:
            if not isinstance(other, InstrFieldMatch):
                raise TypeError(
                    f"InstrFieldMatch.union expects InstrFieldMatch, "
                    f"got {type(other).__name__}")
        union_name = name or "+".join(f.name for f in fields)
        # Flattened in ARGUMENT order, each field's own segment order intact:
        # `a | b` and `b | a` are different rules.
        union_segs = tuple(seg for f in fields for seg in f.match_idx)

        return InstrFieldMatch(union_name, union_segs)

    def __or__(self, other: "InstrFieldMatch") -> "InstrFieldMatch":
        return self.union(other)

    @property
    def width(self) -> int:
        """Total bits this rule matches."""
        return sum(end - start for start, end in self.match_idx)


@dataclass(frozen=True)
class InstrValueMatch:
    match_value : Tuple[int, ...]   # one value per segment of the field it is paired with, same order

    def __post_init__(self):
        if len(self.match_value) == 0:
            raise IndexError("InstrValueMatch must has at least one match_value")
        for value in self.match_value:
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(
                    f"InstrValueMatch match_value must be ints, "
                    f"got {value!r}")
            if value < 0:
                raise ValueError(
                    f"InstrValueMatch match_value {value} is negative — "
                    f"a match value is a bit pattern, not a number")

    def union(self, *others: "InstrValueMatch") -> "InstrValueMatch":
        """One value rule covering this rule's values and the others'.

        Used in step with InstrFieldMatch.union: union the fields in one order
        and the values in the same one, and the segment↔value pairing survives.
        """
        rules = (self,) + others
        for other in others:
            if not isinstance(other, InstrValueMatch):
                raise TypeError(
                    f"InstrValueMatch.union expects InstrValueMatch, "
                    f"got {type(other).__name__}")
        union_value = tuple(v for r in rules for v in r.match_value)

        return InstrValueMatch(union_value)

    def __or__(self, other: "InstrValueMatch") -> "InstrValueMatch":
        return self.union(other)


def check_matcher_pair(matcher_field : Optional[InstrFieldMatch],
                       matcher_value : Optional[InstrValueMatch],
                       where         : str = "matcher") -> None:
    """Hold a (field, value) matcher pair to each other: one value per
    segment, each narrow enough for the segment it is compared against.
    `where` names the holder for the error message.

    A field alone is legal (bit positions, nothing tested yet). A value alone
    is not: it says nothing until a field says which bits it tests.
    """
    if matcher_field is not None and not isinstance(matcher_field, InstrFieldMatch):
        raise TypeError(
            f"{where}: matcher_field must be an InstrFieldMatch, "
            f"got {type(matcher_field).__name__}")
    if matcher_value is None:
        return
    if not isinstance(matcher_value, InstrValueMatch):
        raise TypeError(
            f"{where}: matcher_value must be an InstrValueMatch, "
            f"got {type(matcher_value).__name__}")
    if matcher_field is None:
        raise ValueError(
            f"{where}: matcher_value with no matcher_field — a value says "
            f"nothing until a field says which bits it tests")

    values, segments = matcher_value.match_value, matcher_field.match_idx
    if len(values) != len(segments):
        raise ValueError(
            f"{where}: {len(values)} match values for {len(segments)} segments "
            f"of '{matcher_field.name}' — state one value per segment, in the "
            f"order the segments are written")
    for value, (start, end) in zip(values, segments):
        if value.bit_length() > end - start:
            raise ValueError(
                f"{where}: match value {value:#b} does not fit segment "
                f"({start}, {end}) of '{matcher_field.name}', "
                f"{end - start} bits wide")


