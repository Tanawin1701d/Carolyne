# RV32I immediate extraction — what each immediate's bits MEAN, beside the
# field_match rules that say WHERE they sit.
#
# One body per immediate form, each reading like the spec's own table: a
# placement per segment, then one sign extension. A body WRITES through the
# api and returns nothing; the engine owns the result wire.
#
# The bodies state their bit positions directly (the ISA manual's numbering),
# so a rule reads on its own without chasing a segment list.
#
# SHAMT states no rule: five contiguous bits, zero-extended, which is exactly
# the one case extract_imm_value handles without one.

from __future__ import annotations

from typing import Any

from ..imm_api import ImmApi


def imm_i(word: Any, api: ImmApi) -> None:
    """I-type: word[31:20] -> imm[11:0], sign-extended."""
    api.place(word, 31, 20, at=0)
    api.sign_extend(from_bit=11)


def imm_s(word: Any, api: ImmApi) -> None:
    """S-type: the same 12 bits, split across the rd and funct7 slots."""
    api.place(word, 31, 25, at=5)
    api.place(word, 11,  7, at=0)
    api.sign_extend(from_bit=11)


def imm_b(word: Any, api: ImmApi) -> None:
    """B-type: 13 bits, bit 0 implicitly zero — a branch target is even."""
    api.place(word, 31, 31, at=12)
    api.place(word,  7,  7, at=11)
    api.place(word, 30, 25, at= 5)
    api.place(word, 11,  8, at= 1)
    api.sign_extend(from_bit=12)


def imm_u(word: Any, api: ImmApi) -> None:
    """U-type: word[31:12] -> imm[31:12], low 12 bits zero.

    No sign extension: the field's top bit already IS bit 31 of the value.
    """
    api.place(word, 31, 12, at=12)


def imm_j(word: Any, api: ImmApi) -> None:
    """J-type: 21 bits, bit 0 implicitly zero — a jump target is even."""
    api.place(word, 31, 31, at=20)
    api.place(word, 19, 12, at=12)
    api.place(word, 20, 20, at=11)
    api.place(word, 30, 21, at= 1)
    api.sign_extend(from_bit=20)
