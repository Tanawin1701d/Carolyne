# Layout — the encoding metadata of one instruction group (uop_contract.md
# §1.3): which instruction words the group matches, and where the named
# fields a µop template refers to live inside those bits. Pure data — the
# decoder tree (Kathryn pick/zcase over match/mask) is GENERATED from this;
# the ISA package never writes hardware.
#
# Decisions (2026-08-13):
# - A Field is a tuple of (hi, lo) SEGMENTS concatenated MSB-first, not one
#   range: RISC-V B/J immediates are scattered across the word, and an ISA
#   that could not express that would push the fix-up into uarch — a contract
#   bug by definition. A bare (hi, lo) pair is accepted for the common
#   one-piece field, which is what most fields are.
# - `signed` rides on the Field because sign-extension is part of the
#   extraction rule itself (RISC-V imm12 is signed, rs1 is not), not a
#   separate decode-stage concern.
# - Two self-contradiction checks, because both silently generate a wrong
#   decoder: `match` may not carry bits outside `mask`, and a field may not
#   overlap `mask` (its bits are already pinned by the opcode, so it would
#   extract a constant). Fields MAY overlap each other — x86 wants both the
#   whole ModR/M byte and its mod/reg/rm sub-fields.

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple


@dataclass(frozen=True)
class Field:
    name     : str
    segments : Tuple[Tuple[int, int], ...]      # (hi, lo) MSB-first, concatenated
    signed   : bool = False                     # sign-extend on extraction

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Field needs a non-empty name")
        segments = self.segments
        if (isinstance(segments, tuple) and len(segments) == 2
                and all(isinstance(b, int) for b in segments)):
            segments = (segments,)              # bare (hi, lo) -> one segment
        segments = tuple(tuple(seg) for seg in segments)
        object.__setattr__(self, "segments", segments)
        if not segments:
            raise ValueError(f"Field '{self.name}': needs at least one (hi, lo) segment")
        seen = 0
        for seg in segments:
            if len(seg) != 2:
                raise ValueError(f"Field '{self.name}': segments are (hi, lo) pairs, got {seg}")
            hi, lo = seg
            if not (isinstance(hi, int) and isinstance(lo, int)):
                raise TypeError(f"Field '{self.name}': segment bounds must be ints, got {seg}")
            if lo < 0 or hi < lo:
                raise ValueError(f"Field '{self.name}': bad segment ({hi}, {lo}), need hi >= lo >= 0")
            bits = self.segment_mask(hi, lo)
            if seen & bits:
                raise ValueError(f"Field '{self.name}': segment ({hi}, {lo}) overlaps an earlier one")
            seen |= bits

    @staticmethod
    def segment_mask(hi: int, lo: int) -> int:
        return ((1 << (hi - lo + 1)) - 1) << lo

    @property
    def width(self) -> int:
        # Concatenated width — what the µop record's imm/index field must hold.
        return sum(hi - lo + 1 for hi, lo in self.segments)

    @property
    def bit_mask(self) -> int:
        # Every instruction bit this field reads, as one mask.
        mask = 0
        for hi, lo in self.segments:
            mask |= self.segment_mask(hi, lo)
        return mask

    @property
    def is_split(self) -> bool:
        return len(self.segments) > 1


@dataclass(frozen=True)
class Layout:
    width  : int                                # instruction width in bits
    match  : int                                # opcode bits, under mask
    mask   : int                                # which bits `match` constrains
    fields : Tuple[Field, ...] = ()

    def __post_init__(self) -> None:
        if self.width < 1:
            raise ValueError(f"Layout: width must be >= 1, got {self.width}")
        object.__setattr__(self, "fields", _as_fields(self.fields))
        limit = 1 << self.width
        for label, value in (("mask", self.mask), ("match", self.match)):
            if not (0 <= value < limit):
                raise ValueError(
                    f"Layout: {label} {value:#x} does not fit in {self.width} bits")
        if self.match & ~self.mask:
            raise ValueError(
                f"Layout: match {self.match:#x} sets bits outside mask {self.mask:#x} "
                f"(stray: {self.match & ~self.mask:#x}) — those bits constrain nothing")
        names = set()
        for fld in self.fields:
            if fld.name in names:
                raise ValueError(f"Layout: duplicate field name '{fld.name}'")
            names.add(fld.name)
            if fld.bit_mask >= limit:
                raise ValueError(
                    f"Layout: field '{fld.name}' reads bits outside the {self.width}-bit word")
            if fld.bit_mask & self.mask:
                raise ValueError(
                    f"Layout: field '{fld.name}' overlaps mask {self.mask:#x} — those bits are "
                    f"already pinned by match, so the field would decode to a constant")

    @property
    def field_names(self) -> Tuple[str, ...]:
        return tuple(fld.name for fld in self.fields)

    def has(self, name: str) -> bool:
        return any(fld.name == name for fld in self.fields)

    def field(self, name: str) -> Field:
        for fld in self.fields:
            if fld.name == name:
                return fld
        raise KeyError(
            f"Layout has no field '{name}' (has: {', '.join(self.field_names) or 'none'})")

    def matches(self, word: int) -> bool:
        # Elaboration-time helper for tests/tables; the hardware form of this
        # is the generated decoder tree, not this function.
        return word & self.mask == self.match


def _as_fields(fields) -> Tuple[Field, ...]:
    # Accept a {name: (hi, lo)} / {name: Field} mapping or any iterable of Field.
    if isinstance(fields, Mapping):
        out = []
        for name, spec in fields.items():
            if isinstance(spec, Field):
                if spec.name != name:
                    raise ValueError(
                        f"Layout: field keyed '{name}' is named '{spec.name}' — "
                        f"a µop's FieldRef resolves by name, so the two must agree")
                out.append(spec)
            else:
                out.append(Field(name, spec))
        fields = out
    fields = tuple(fields)
    for fld in fields:
        if not isinstance(fld, Field):
            raise TypeError(f"Layout fields must be Field, got {type(fld).__name__}")
    return fields
