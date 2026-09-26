# MIPS32 immediate extraction — what each immediate's bits MEAN, beside the
# field_match rules that say WHERE they are.
#
# One body per immediate form, reading like the manual's own table: a
# placement per segment, then one sign extension. A body WRITES through the
# api and returns nothing; the engine declares the result wire.
#
# The zero-extended forms (andi/ori/xori's imm16, a shift's sa) state no
# rule: one contiguous zero-extended field is the one case extract_imm_value
# handles without one.

from __future__ import annotations

from typing import Any

from ..imm_api import ImmApi


def imm_s16(word: Any, api: ImmApi) -> None:
    """imm16 sign-extended: addi/addiu/slti/sltiu and every load/store offset."""
    api.place(word, 15, 0, at=0)
    api.sign_extend(from_bit=15)


def imm_lui(word: Any, api: ImmApi) -> None:
    """lui: imm16 in the top half, the low half zero."""
    api.place(word, 15, 0, at=16)


def imm_br(word: Any, api: ImmApi) -> None:
    """A branch offset: imm16 << 2, sign-extended — added to the pc of the delay slot."""
    api.place(word, 15, 0, at=2)
    api.sign_extend(from_bit=17)


def imm_j(word: Any, api: ImmApi) -> None:
    """j/jal: instr_index << 2; the top four bits come from the pc (exec_unit_br.py)."""
    api.place(word, 25, 0, at=2)


def imm_bitfield(word: Any, api: ImmApi) -> None:
    """ext/ins: the sa field at bits 4..0 and the rd field at bits 12..8, one value.

    - ext reads pos then size-1, ins reads lsb then msb; the body slices them
    """
    api.place(word, 10,  6, at=0)
    api.place(word, 15, 11, at=8)
