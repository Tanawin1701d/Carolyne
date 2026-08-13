# Mop — one macro-op group: the encoding metadata that maps an instruction
# layout to the µop sequence(s) it cracks into. This is where uop_contract.md
# §1.3 (encoding table) and §1.4 (crackers) meet, and it is the layer
# field_ref.py deferred its existence check to — a Uop's FieldRef("rs1") is
# only checkable as a *real* field once a cracker is bound to a layout, which
# happens here.
#
# Shape (decided 2026-08-13) — a Mop is a list of lists:
#   outer (variants) : alternatives under ONE layout, each selected by the
#                      value of discriminating fields. RISC-V R-type declares
#                      rd/rs1/rs2 once and lets funct3/funct7 pick
#                      ADD/SUB/AND/...; declaring the register field positions
#                      once per family member is exactly the boilerplate this
#                      kills.
#   inner (uops)     : the µop sequence of one instruction, fired in order
#                      (§1.4: a linear 1..N sequence, not a DAG — Q3;
#                      x86 `add [m], r` -> AGU / LOAD / ADD / STORE).
#
# Decisions (2026-08-13):
# - `when` maps field name -> required value, EXTENDING the layout's
#   match/mask for that variant. Variants must be pairwise distinguishable —
#   two that agree on every shared key could both match one instruction word,
#   which is an ambiguous decoder, so it raises. A lone variant may have an
#   empty `when` (the layout's match/mask already pins the instruction, e.g.
#   x86 `ret`); that only becomes ambiguous once a second variant exists,
#   and the pairwise rule catches it for free.
# - first/last (`bound`, §2) is NOT stored on Uop: it is a property of a
#   template's POSITION, so the sequence derives it here (`bounds`). Commit
#   retires at instruction granularity off these bits (§4.4).
# - µtemp discipline is enforced here, since a sequence is the scope an
#   Intermediate lives in (§1.4: dead at the instruction boundary *by
#   construction*): read-before-write, written-twice, and written-never-read
#   all raise. Each is a cracker wiring bug that would otherwise surface as
#   silently wrong hardware.
# - The op-per-instruction question settled in uop.py stays settled: a
#   variant carries concrete Uops. Per-ISA packages build the repetitive ones
#   with a factory function (see tests) — Python is the templating mechanism.

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Dict, Iterator, Tuple

from .field_ref import FieldRef
from .layout import Layout
from .uop import Uop


@dataclass(frozen=True)
class Variant:
    """One alternative of a Mop: a discriminator plus the µop sequence it runs."""
    when : Dict[str, int] = dc_field(default_factory=dict)  # field name -> required value
    uops : Tuple[Uop, ...] = ()                             # fired in order

    def __post_init__(self) -> None:
        object.__setattr__(self, "uops", tuple(self.uops))
        if not self.uops:
            raise ValueError(f"{self.label}: needs at least one µop")
        for uop in self.uops:
            if not isinstance(uop, Uop):
                raise TypeError(f"{self.label}: uops must be Uop, got {type(uop).__name__}")
        for name, value in self.when.items():
            if not name:
                raise ValueError(f"{self.label}: `when` keys must be field names")
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(
                    f"{self.label}: `when['{name}']` must be an int, got {type(value).__name__}")
            if value < 0:
                raise ValueError(f"{self.label}: `when['{name}']` must be >= 0, got {value}")
        self._check_temps()

    def _check_temps(self) -> None:
        # Intermediate uses eq=False, so identity IS the value node (see
        # intermediate.py) and a plain set tracks defs exactly.
        written, read = set(), set()
        for pos, uop in enumerate(self.uops):
            for src in uop.srcs:
                if src.is_intermediate:
                    if src.target not in written:
                        raise ValueError(
                            f"{self.label}: µop {pos} ({uop.unit.name}.{uop.op}) reads µtemp "
                            f"{_temp(src.target)} before any earlier µop writes it")
                    read.add(src.target)
            for dest in uop.dests:
                if dest.is_intermediate:
                    if dest.target in written:
                        raise ValueError(
                            f"{self.label}: µop {pos} ({uop.unit.name}.{uop.op}) rewrites µtemp "
                            f"{_temp(dest.target)} — reuse of one instance means one value node, "
                            f"use a second Intermediate for a second value")
                    written.add(dest.target)
        dangling = written - read
        if dangling:
            names = ", ".join(sorted(_temp(t) for t in dangling))
            raise ValueError(
                f"{self.label}: µtemp(s) {names} written but never read — a µtemp is dead at "
                f"the instruction boundary, so nothing outside the sequence can consume it")

    @property
    def label(self) -> str:
        keys = ", ".join(f"{k}={v:#x}" for k, v in sorted(self.when.items()))
        return f"Variant({keys})" if keys else "Variant(default)"

    @property
    def bounds(self) -> Tuple[Tuple[bool, bool], ...]:
        """Per-µop (first, last) — the §2 `bound` field, derived from position."""
        last = len(self.uops) - 1
        return tuple((pos == 0, pos == last) for pos in range(len(self.uops)))

    @property
    def is_cracked(self) -> bool:
        """More than one µop — the multi-µop path that stalls fetch (§3)."""
        return len(self.uops) > 1

    def distinguishable_from(self, other: "Variant") -> bool:
        # Decode can tell them apart only if some field both constrain
        # disagrees; otherwise one word could satisfy both.
        return any(key in other.when and other.when[key] != value
                   for key, value in self.when.items())


@dataclass(frozen=True)
class Mop:
    """An instruction group: one layout, one or more µop sequences under it."""
    name     : str                          # group/mnemonic, e.g. "R-TYPE", "ADD"
    layout   : Layout
    variants : Tuple[Variant, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Mop needs a non-empty name")
        if not isinstance(self.layout, Layout):
            raise TypeError(f"Mop '{self.name}': layout must be a Layout, "
                            f"got {type(self.layout).__name__}")
        object.__setattr__(self, "variants", tuple(self.variants))
        if not self.variants:
            raise ValueError(f"Mop '{self.name}': needs at least one variant")
        for variant in self.variants:
            if not isinstance(variant, Variant):
                raise TypeError(f"Mop '{self.name}': variants must be Variant, "
                                f"got {type(variant).__name__}")
            self._check_discriminator(variant)
            self._check_field_refs(variant)
        for i, left in enumerate(self.variants):
            for right in self.variants[i + 1:]:
                if not left.distinguishable_from(right):
                    raise ValueError(
                        f"Mop '{self.name}': {left.label} and {right.label} are not "
                        f"distinguishable — one instruction word could select either")

    def _check_discriminator(self, variant: Variant) -> None:
        for name, value in variant.when.items():
            if not self.layout.has(name):
                raise ValueError(
                    f"Mop '{self.name}': {variant.label} keys on '{name}', which the layout "
                    f"does not declare (has: {', '.join(self.layout.field_names) or 'none'})")
            fld = self.layout.field(name)
            if value >= (1 << fld.width):
                raise ValueError(
                    f"Mop '{self.name}': {variant.label} wants {name}={value:#x}, which does "
                    f"not fit the field's {fld.width} bits")

    def _check_field_refs(self, variant: Variant) -> None:
        # The check field_ref.py promised: a FieldRef is only a name until a
        # cracker meets an encoding, and this is that meeting point.
        for pos, uop in enumerate(variant.uops):
            for ref in _field_refs(uop):
                if not self.layout.has(ref.name):
                    raise ValueError(
                        f"Mop '{self.name}': {variant.label} µop {pos} "
                        f"({uop.unit.name}.{uop.op}) refers to field '{ref.name}', which the "
                        f"layout does not declare "
                        f"(has: {', '.join(self.layout.field_names) or 'none'})")

    @property
    def is_family(self) -> bool:
        """Several instructions share this layout (RISC-V R-type)."""
        return len(self.variants) > 1

    @property
    def max_uops(self) -> int:
        """Longest crack — how deep the front-end's expander must go (§3)."""
        return max(len(v.uops) for v in self.variants)

    def select(self, word: int) -> Variant:
        """Elaboration-time reference decode, for tests and table checks: the
        hardware form is the GENERATED decoder tree, never this function."""
        if not self.layout.matches(word):
            raise KeyError(f"Mop '{self.name}': word {word:#x} does not match the layout")
        for variant in self.variants:
            if all(self.extract(word, name) == value for name, value in variant.when.items()):
                return variant
        raise KeyError(f"Mop '{self.name}': word {word:#x} matches the layout but no variant")

    def extract(self, word: int, name: str) -> int:
        """Reference field extraction (see `select`): segments concatenate
        MSB-first, so a split RISC-V B/J immediate reassembles in order."""
        value = 0
        for hi, lo in self.layout.field(name).segments:      # MSB-first concatenation
            value = (value << (hi - lo + 1)) | ((word >> lo) & ((1 << (hi - lo + 1)) - 1))
        return value


def _field_refs(uop: Uop) -> Iterator[FieldRef]:
    for operand in (*uop.srcs, *uop.dests):
        if isinstance(operand.index, FieldRef):
            yield operand.index
    if isinstance(uop.imm, FieldRef):
        yield uop.imm


def _temp(target) -> str:
    return f"'{target.name}'" if target.name else f"<unnamed {target.width}b>"
