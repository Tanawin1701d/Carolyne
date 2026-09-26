# Helpers every ISA's exec_stage body is written over — the sanctioned
# Kathryn of the description layer (CLAUDE.md §2), shared by the packages.
#
# A unit body is a flat (µops, value) table over uop_hit / drive_by_uop, so
# adding a µop to a unit is one table row. The sub-word helpers are the
# little-endian byte and halfword arithmetic a load/store body needs; they
# name no ISA constant, so any 32-bit-word ISA reads its bytes the same way.

from __future__ import annotations

from kathryn import val, zif
from kathryn.signal import to_ref

from .uop import Uop


# --- the µop guard ------------------------------------------------------------
def uop_hit(src, uops):
    """The record holds any of these µops: one OR-ed guard over the group,
    compared against the `uop_idx` field the record already has. A group is
    one operation encoded twice (add/addi), so it shares one guard."""
    hit = None
    for uop in ((uops,) if isinstance(uops, Uop) else uops):
        term = to_ref(src[0].uop_idx) == uop.uop_idx
        hit  = term if hit is None else hit | term
    return hit


def drive_by_uop(result, src, cases) -> None:
    """Drive `result` from a (µops, value) table: one zif per row.

    - every value is COMPUTED whatever the µop is; the guard only picks"""
    for uops, value in cases:
        with zif(uop_hit(src, uops)):
            result *= value


# --- sub-word access inside a 32-bit little-endian word -----------------------
# `eff_addr` counts BYTES and memory is addressed by WORDS: the low two bits
# pick the byte inside the word. `<< 3` turns a byte offset into a bit one.
def sub_word_bit_offsets(eff_addr):
    """(byte_bit_off, half_bit_off): 0/8/16/24 and 0/16 for this address."""
    return (eff_addr & 0b11) << 3, (eff_addr & 0b10) << 3


def merge_byte(word, data, byte_bit_off, width: int):
    """`word` with its addressed byte replaced by data's low byte."""
    mask = val(width, 0xff) << byte_bit_off
    return (word & ~mask) | ((data & 0xff) << byte_bit_off)


def merge_half(word, data, half_bit_off, width: int):
    """`word` with its addressed halfword replaced by data's low halfword."""
    mask = val(width, 0xffff) << half_bit_off
    return (word & ~mask) | ((data & 0xffff) << half_bit_off)


def extract_byte(word, byte_bit_off):  return (word >> byte_bit_off) & 0xff
def extract_half(word, half_bit_off):  return (word >> half_bit_off) & 0xffff
def sext_byte   (v)                   :  return (v ^ 0x80)   - 0x80      # sign extension by wraparound
def sext_half   (v)                   :  return (v ^ 0x8000) - 0x8000
