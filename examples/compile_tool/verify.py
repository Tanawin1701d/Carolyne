# Holding a compiled program to the ISA description.
#
# Every instruction word in an executable section is decoded with the
# project's OWN encoding table — the same `group_uops_by_level(isa)` grouping
# the hardware decoder builds its guards from, and the same
# `match_field_bits` it compares with, on the int path. So this asks exactly
# the question the silicon will ask: does this word pick one µop?
#
# Three answers are failures:
#   no match    the machine decodes this word into nothing and the lane goes
#               out as an empty entry — an instruction the ISA has not got
#   ambiguous   two µops claim it, so what executes is not defined
#   delay slot  the word after a µop carrying the "delay_slot" feature is not
#               the nop the target demands there. The engine does not execute
#               a delay slot yet: a taken branch squashes the word after it,
#               so only a nop may stand there (compile with
#               -fno-delayed-branch). A target with no such rule
#               (`delay_slot_nop=None`) is not checked.
#
# This is what makes a flag safe to offer before the description has the
# µops: the build fails naming the word instead of producing an image the
# core silently drops.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from carolyne.isa import IsaBase
from carolyne.uarch.common import match_field_bits
from carolyne.uarch.o3.decode import group_uops_by_level

from .elf32 import Elf32

# how many bad words to name before the message is just noise
_MAX_REPORTED = 12

# the µop feature a description puts on a branch whose next word always
# executes; the engine will read it one day, the tool holds it to a nop today
DELAY_SLOT_FEATURE = "delay_slot"


# --- one bad word -------------------------------------------------------------
@dataclass(frozen=True)
class Problem:
    """One instruction word the ISA description cannot accept."""

    addr    : int
    word    : int
    section : str
    kind    : str                        # "no match" | "ambiguous" | "delay slot"
    hits    : Tuple[str, ...] = ()       # the µops that claimed the word
    slot    : Optional[int]   = None     # delay slot: the word found there; None past the section's end

    def __str__(self) -> str:
        if self.kind == "ambiguous":
            detail = f"claimed by {', '.join(self.hits)}"
        elif self.kind == "no match":
            detail = "matches no µop in the ISA"
        elif self.slot is None:
            detail = f"{self.hits[0]} is the section's last word: its delay slot is missing"
        else:
            detail = f"{self.hits[0]}'s delay slot holds {self.slot:08x}, not the nop"
        return (f"0x{self.addr:08x}  {self.word:08x}  "
                f"[{self.section}]  {detail}")


# --- the result ---------------------------------------------------------------
@dataclass(frozen=True)
class VerifyReport:
    """What decoding the whole program found."""

    isa_name : str
    checked  : int
    problems : Tuple[Problem, ...]
    skipped  : bool = False       # no description to hold the program to (target.py says which)

    @classmethod
    def not_verified(cls, target_name: str) -> "VerifyReport":
        return cls(isa_name=f"(no ISA description for {target_name})", checked=0,
                   problems=(), skipped=True)

    @property
    def ok(self) -> bool: return not self.problems

    def raise_if_bad(self) -> "VerifyReport":
        """Refuse a program the machine could not run, naming the words."""
        if self.ok:
            return self

        shown = self.problems[:_MAX_REPORTED]
        more  = len(self.problems) - len(shown)
        lines = "\n  ".join(str(p) for p in shown)
        tail  = f"\n  ... and {more} more" if more else ""
        raise ValueError(
            f"{len(self.problems)} of {self.checked} instructions cannot be "
            f"accepted by {self.isa_name}:\n  {lines}{tail}\n"
            f"Either the program uses an extension the ISA description has "
            f"not got, the encoding table is incomplete, or a branch delay slot "
            f"holds an instruction (compile with -fno-delayed-branch).")

    def describe(self) -> str:
        if self.skipped:
            return f"not verified: {self.isa_name}"
        return (f"verified {self.checked} instructions against "
                f"{self.isa_name}: {'ok' if self.ok else 'FAILED'}")


# --- checking -----------------------------------------------------------------
def decode_hits(word: int, levels) -> Tuple:
    """Every µop whose encoding rules hold for this word, at the first level.

    The conjunction is the mop's rule and the uop_seq's rule together, which
    is the whole encoding side — a template carries no matcher of its own.
    """
    hits = []
    for matchers, uop in levels[0]:
        if all(match_field_bits(word, field, value)
               for field, value in matchers):
            hits.append(uop)
    return tuple(hits)


def verify_program(elf: Elf32, isa: IsaBase,
                   delay_slot_nop: Optional[int] = None) -> VerifyReport:
    """Decode every instruction of every executable section.

    - `delay_slot_nop`: the word that must follow every µop carrying the
      "delay_slot" feature, or None when the machine executes the slot
    """
    levels   = group_uops_by_level(isa)
    width    = isa.ilen_bytes
    problems = []
    checked  = 0

    for section in elf.alloc_sections():
        if not section.is_exec:
            continue
        blob  = elf.bytes_of(section)
        words = [int.from_bytes(blob[offset:offset + width], "little")
                 for offset in range(0, len(blob) - width + 1, width)]
        for index, word in enumerate(words):
            checked += 1
            at   = section.addr_target_mem + index * width
            hits = decode_hits(word, levels)
            if len(hits) != 1:
                problems.append(Problem(addr=at, word=word, section=section.name,
                                        kind="ambiguous" if hits else "no match",
                                        hits=tuple(u.name for u in hits)))
                continue
            if delay_slot_nop is None or not hits[0].has_feature(DELAY_SLOT_FEATURE):
                continue
            slot = words[index + 1] if index + 1 < len(words) else None
            if slot != delay_slot_nop:
                problems.append(Problem(addr=at, word=word, section=section.name,
                                        kind="delay slot", hits=(hits[0].name,), slot=slot))

    return VerifyReport(isa_name = isa.name,
                        checked  = checked,
                        problems = tuple(problems))
