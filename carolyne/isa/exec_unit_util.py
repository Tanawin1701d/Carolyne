# Helpers every ISA's exec_stage body is written over — the sanctioned
# Kathryn of the description layer (CLAUDE.md §2), shared by the packages.
#
# A unit body is a flat (µops, value) table over uop_hit / drive_by_uop, so
# adding a µop to a unit is one table row. The sub-word helpers are the
# little-endian byte and halfword arithmetic a load/store body needs; they
# name no ISA constant, so any 32-bit-word ISA reads its bytes the same way.
# The restoring-divider helpers are the state and the steps a multi-stage
# div unit is built from; the unit decides how many steps one stage holds.

from __future__ import annotations

from kathryn import HwComponentType, Karray, kaf, mux, val, zif
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


# --- the restoring divider, one stage at a time --------------------------------
# A division of `width` bits is `width` restoring steps: shift one dividend bit
# into the partial remainder, subtract the divisor, keep the difference when it
# did not borrow. A step is one carry chain, so a stage holds a fixed number of
# them and the state travels in a DivState record between stages.
#
# Signed operands go through magnitudes: the start records which results to
# negate, and div_results puts the signs back. That also gives
# INT_MIN / -1 = INT_MIN with remainder 0, and a zero divisor is answered the
# RISC-V way (quotient all ones, remainder the dividend), where Verilog's `/`
# would give X.

DIV_STEPS_PER_STAGE = 8          # ~9 ns of carry chain: what a 20 ns stage holds with room


class DivState(Karray):
    """What a divide carries between stages: the unit's own data only.

    The machine's fields (speculation pair, ROB entry, µop kind, the promised
    registers) arrive from `api.next_stage_fields` at instantiation.
    """
    dividend = kaf()        # the magnitude being divided (the raw operand when unsigned)
    divisor  = kaf()
    rem      = kaf()        # the partial remainder
    quot     = kaf()        # the quotient bits found so far
    a_raw    = kaf()        # the dividend as given: a remainder by zero returns it
    q_neg    = kaf(1)       # negate the quotient at the end
    r_neg    = kaf(1)       # negate the remainder at the end
    b_zero   = kaf(1)


def div_state_record(name: str, width: int, machine_fields: dict) -> DivState:
    """One stage's DivState, sized for `width`-bit operands, machine fields added."""
    return DivState(HwComponentType.REG, (1,), name,
                    dividend=width, divisor=width, rem=width, quot=width, a_raw=width,
                    **machine_fields)


def div_start(a, b, signed_op, width: int) -> dict:
    """The DivState values a divide begins with: magnitudes, and the signs to put back.

    - `signed_op` is 1 for the signed µops; unsigned ones divide the raw operands
    """
    zero  = val(width, 0)
    a_neg = a[width - 1, width - 1] & signed_op
    b_neg = b[width - 1, width - 1] & signed_op
    return {"dividend": mux(a_neg, zero - a, a),
            "divisor" : mux(b_neg, zero - b, b),
            "rem"     : 0,
            "quot"    : 0,
            "a_raw"   : a,
            "q_neg"   : a_neg ^ b_neg,           # negative when the signs differ
            "r_neg"   : a_neg,                   # the remainder takes the dividend's sign
            "b_zero"  : b == 0}


def div_steps(state, first_bit: int, count: int, width: int) -> dict:
    """`count` restoring steps over dividend bits first_bit downward: the next DivState.

    - a 2-bit-wider subtraction: its top bit is the borrow, which says the
      divisor did not fit and the shifted remainder stands
    """
    dividend, divisor = to_ref(state.dividend), to_ref(state.divisor)
    rem, quot         = to_ref(state.rem), to_ref(state.quot)
    wide              = width + 2
    for i in range(count):
        bit     = first_bit - i
        shifted = (rem.extend(wide) << 1) | dividend[bit, bit].extend(wide)
        diff    = shifted - divisor.extend(wide)
        borrow  = diff[wide - 1, wide - 1]
        rem     = mux(borrow, shifted[width - 1, 0], diff[width - 1, 0])
        quot    = (quot << 1) | (~borrow).extend(width)
    return {"dividend": dividend,
            "divisor" : divisor,
            "rem"     : rem,
            "quot"    : quot,
            "a_raw"   : to_ref(state.a_raw),
            "q_neg"   : to_ref(state.q_neg),
            "r_neg"   : to_ref(state.r_neg),
            "b_zero"  : to_ref(state.b_zero)}


def div_results(state, width: int):
    """(quotient, remainder) of a finished DivState, signs put back, zero divisor answered."""
    zero, ones = val(width, 0), val(width, (1 << width) - 1)
    quot, rem  = to_ref(state.quot), to_ref(state.rem)
    b_zero     = to_ref(state.b_zero)
    quotient   = mux(to_ref(state.q_neg), zero - quot, quot)
    remainder  = mux(to_ref(state.r_neg), zero - rem,  rem)
    return mux(b_zero, ones, quotient), mux(b_zero, to_ref(state.a_raw), remainder)
