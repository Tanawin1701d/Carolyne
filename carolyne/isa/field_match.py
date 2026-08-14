# InstrFieldMatch — where a named encoding field lives in the instruction
# word (uop_contract.md §1.3). One rule, one field: a name plus the bit
# segments it occupies, `(start, end)` with end EXCLUSIVE and bit 0 = LSB.
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
# KNOWN GAPS — both are contract-side, and both block decoder generation:
# - No VALUE. This says WHERE a field is, never what it must EQUAL, so
#   "opcode == 0110011" cannot be written and no two encodings that share a
#   field layout can be told apart.
# - No segment placement. For RISC-V's imm_s, (7,12) is imm[4:0] and (25,32)
#   is imm[11:5]; the type records the segments but not where each lands in
#   the assembled value, nor whether the result is sign-extended.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class InstrFieldMatch:
    name      : str
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
