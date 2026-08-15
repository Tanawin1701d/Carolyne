# InstrFieldMatch — where a named encoding field lives in the instruction
# word (uop_contract.md §1.3). One rule, one field: a name plus the bit
# segments it occupies, `(start, end)` with end EXCLUSIVE and bit 0 = LSB.
# InstrValueMatch is the other half — the values those bits must EQUAL, which
# is what makes an encoding discriminable. It names no field: the two are
# separate rules, paired by whoever holds both.
#
# Decisions (2026-08-14):
# - A TUPLE of segments, because a field need not be contiguous: RISC-V's
#   s/b/j-type immediates are scattered across the word, and x86 fields are
#   split by prefixes. A single (start, end) would force every consumer to
#   special-case the split ones.
# - Lives in its own module rather than inside mop.py. Everything that names
#   a field imports it — Operand, Uop, UopSeq, Mop, and each per-ISA package
#   — so keeping it in mop.py made mop.py a dependency of the whole layer and
#   forced the Uop annotation there to be a stringified TYPE_CHECKING import
#   to dodge the cycle. Split out, the dependency runs one way: field_match
#   → operand/uop → mop.
#
# Decisions (2026-08-15) — InstrValueMatch, the value half:
# - It carries VALUES ONLY, no field. The two halves stay separate types the
#   way "where a field is" and "which index reads it" already are (Operand's
#   FieldRef vs its matcher): a value rule is a bit pattern, and which bits it
#   is compared against is stated by whatever pairs the two. Consequence —
#   neither type can check the pairing, so the HOLDER of both does it:
#   `check_matcher_pair` at the bottom of this file, called by Uop, UopSeq and
#   Mop, is where "one value per segment, each narrow enough for its segment"
#   is enforced.
# - The holders name the halves SEPARATELY: `matcher_field` and
#   `matcher_value`, two slots, rather than one slot typed as either. Two
#   slots is what makes the pair checkable at all — a single either-typed slot
#   can hold a value with no field to test it against — and a field with no
#   value is then just the value slot left None, which is exactly the state
#   RV32I is in today.
# - ONE VALUE PER SEGMENT of the field it pairs with, in the same order — not
#   one assembled integer. The segments of a scrambled field land in unrelated
#   places and the type cannot yet say where (see GAPS), so an assembled value
#   would have no defined layout to be assembled INTO. Per segment, add vs sub
#   reads the way the spec table does: `(funct3, funct7)`.
# - `union` mirrors InstrFieldMatch.union and is meant to be used in step with
#   it — union the fields in one order, the values in the same one, and the
#   segment↔value pairing survives. Same append-only rule, same reason.
# - No `matches(word)` method. Evaluating a rule against an instruction word
#   is a runtime act; this layer holds the rule and the generator builds the
#   comparator (CLAUDE.md §2 — no runtime value ever lives in the ISA layer).
#
# KNOWN GAPS — contract-side, and still blocking decoder generation:
# - No segment placement. For RISC-V's imm_s, (7,12) is imm[4:0] and (25,32)
#   is imm[11:5]; the type records the segments but not where each lands in
#   the assembled value, nor whether the result is sign-extended. This is why
#   InstrValueMatch counts values per segment rather than assembling one.
# - Nothing REQUIRES a value. `matcher_value` defaults to None at every
#   holder, so an encoding that supplies only field positions is still
#   accepted — which is what RV32I does today. Whether a DECODABLE ISA must
#   supply values throughout is a contract call, and the place to enforce it
#   is IsaBase, which sees the whole table.
# The first gap here — no VALUE at all — is closed by InstrValueMatch, and
# where a value binds to a field is answered by the matcher_field /
# matcher_value pair on Uop, UopSeq and Mop.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class InstrFieldMatch:
    name      : str
    # ORDER IS SIGNIFICANT — the tuple is the caller's statement about the field,
    # not a set of bits: nothing here sorts, merges or dedups it, and consumers
    # must read it in the order written (imm_b: (7,8) is imm[11], (8,12) is imm[4:1]).
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
        # Flattened in ARGUMENT order, each field's own segment order kept intact:
        # `a | b` and `b | a` are different rules, not the same one.
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

        The counterpart of InstrFieldMatch.union, and used in step with it:
        union the fields in one order and the values in the same one, and the
        segment↔value pairing survives the merge (add vs sub = funct3's value
        then funct7's).
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
    """Hold a (field, value) matcher pair to each other.

    The two halves are separate types that know nothing of one another, so a
    holder of BOTH — Uop, UopSeq, Mop — is the only place the pairing can be
    checked: one value per segment, each narrow enough for the segment it is
    compared against. `where` names the holder for the error message.

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


