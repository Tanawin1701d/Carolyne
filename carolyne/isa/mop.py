from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:                   # operand/uop import InstrFieldMatch from here,
    from .uop import Uop            # so Uop may only be a (stringified) annotation


@dataclass(frozen=True)
class InstrFieldMatch:
    name      : str
    match_idx : Tuple[Tuple[int, int], ...]  # ((start_match_idx, end_match_idx), ...), end exclusive

    def __post_init__(self):
        if len(self.match_idx) == 0:
            raise IndexError("MopFieldMatch must has at least one (start_match_idx, end_match_idx)")
        for seg in self.match_idx:  # a bare (start, end) pair trips this, not the unpack below
            if not isinstance(seg, tuple) or len(seg) != 2:
                raise IndexError(
                    f"MopFieldMatch match_idx must be a tuple of (start_match_idx, end_match_idx), got {seg!r}")
            start_match_idx, end_match_idx = seg
            if start_match_idx >= end_match_idx:
                raise IndexError("MopFieldMatch must has start_match_idx < end_match_idx")

@dataclass(frozen=True)
class UopSeq:
    uops : Tuple[Uop, ...] = ()

    def __post_init__(self):
        if len(self.uops) == 0:
            raise IndexError("uop sequence must have at least one uop")


@dataclass(frozen=True)
class Mop:
    matcher : Tuple[InstrFieldMatch, ...] = () # preliminary matcher
    uop_seq : Tuple[UopSeq, ...] = ()

    def __post_init__(self):
        if len(self.uop_seq) == 0:
            raise IndexError("Mop must have at least one uop")

        if len(self.matcher) == 0:
            raise IndexError("Mop must have at least one matcher")

