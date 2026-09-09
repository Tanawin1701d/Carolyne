# Holding a compiled program to the ISA description.
#
# Every instruction word in an executable section is decoded with the
# project's OWN encoding table — the same `group_uops_by_level(isa)` grouping
# the hardware decoder builds its guards from, and the same
# `match_field_bits` it compares with, on the int path. So this asks exactly
# the question the silicon will ask: does this word pick one µop?
#
# Two answers are failures:
#   no match   the machine decodes this word into nothing and the lane goes
#              out as an empty entry — an instruction the ISA has not got
#   ambiguous  two µops claim it, so what executes is not defined
#
# This is what makes `-march=rv32im` safe to offer before the description has
# multiply µops: the build fails naming the MUL instead of producing an image
# the core silently drops. When M is added to carolyne/isa/riscv/, the same
# check starts passing with no change here.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from carolyne.isa import IsaBase
from carolyne.uarch.common import match_field_bits
from carolyne.uarch.o3.decode import group_uops_by_level

from .elf32 import Elf32

# how many bad words to name before the message is just noise
_MAX_REPORTED = 12


# --- one bad word -------------------------------------------------------------
@dataclass(frozen=True)
class Problem:
    """One instruction word the ISA description cannot decode."""

    addr    : int
    word    : int
    section : str
    hits    : Tuple[str, ...]

    @property
    def kind(self) -> str:
        return "ambiguous" if self.hits else "no match"

    def __str__(self) -> str:
        detail = (f"claimed by {', '.join(self.hits)}" if self.hits
                  else "matches no µop in the ISA")
        return (f"0x{self.addr:08x}  {self.word:08x}  "
                f"[{self.section}]  {detail}")


# --- the result ---------------------------------------------------------------
@dataclass(frozen=True)
class VerifyReport:
    """What decoding the whole program found."""

    isa_name : str
    checked  : int
    problems : Tuple[Problem, ...]

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
            f"decoded by {self.isa_name}:\n  {lines}{tail}\n"
            f"Either the program uses an extension the ISA description has "
            f"not got, or the encoding table is incomplete.")

    def describe(self) -> str:
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


def verify_program(elf: Elf32, isa: IsaBase) -> VerifyReport:
    """Decode every instruction of every executable section."""
    levels   = group_uops_by_level(isa)
    width    = isa.ilen_bytes
    problems = []
    checked  = 0

    for section in elf.alloc_sections():
        if not section.is_exec:
            continue
        blob = elf.bytes_of(section)
        for offset in range(0, len(blob) - width + 1, width):
            word = int.from_bytes(blob[offset:offset + width], "little")
            checked += 1
            hits = decode_hits(word, levels)
            if len(hits) != 1:
                at = section.addr_target_mem + offset
                problems.append(Problem(addr    = at,
                                        word    = word,
                                        section = section.name,
                                        hits    = tuple(u.name for u in hits)))

    return VerifyReport(isa_name = isa.name,
                        checked  = checked,
                        problems = tuple(problems))
