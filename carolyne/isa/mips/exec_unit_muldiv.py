# MulDivExecUnit — the HI/LO accumulator's instructions, in one combinational
# stage: mult/multu/div/divu write both halves, mul writes rd, mfhi/mflo
# move a half to rd, mthi/mtlo move rs into a half.
#
# Kathryn's `*`, `/` and `%` take the LEFT operand's width, so:
# - the low word is `a * b` on the 32-bit operands; the high words come from
#   operands widened to 2 * X_LEN first, a signed one by a mux fill
# - `/` and `%` are unsigned: DIV goes through magnitudes and a sign fix,
#   which also gives INT_MIN / -1 = INT_MIN with remainder 0
# - a divisor of zero is UNPREDICTABLE in MIPS; the mux gives the RISC-V
#   answers (quotient all ones, remainder the dividend), since Verilog would
#   give X
#
# EVERY writeback is GATED on the µops that write that destination: a µop
# that does not write a slot booked no physical register for it, and an
# unguarded write would land on a garbage pr_idx.
#
# LIMIT: a 32-bit combinational divider bounds fmax until a sequential
# divider replaces it — the station keeps it off the ALUs' path.

from __future__ import annotations

from kathryn import mux, val, wire, zif
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from ..exec_unit_util import drive_by_uop, uop_hit
from . import uop as U
from .operand import (AOPR_DEST_1, AOPR_DEST_HI, AOPR_DEST_LO, AOPR_SRC_1, AOPR_SRC_2,
                      AOPR_SRC_HI, AOPR_SRC_LO)
from .reg import X_LEN

WIDE = 2 * X_LEN


class MulDivExecUnit(ExecUnitBase):
    """mult / multu / div / divu / mul / mfhi / mflo / mthi / mtlo, one stage."""

    def exec_stage(self, stage_idx, src, api):
        a  = to_ref(api.get_src(src, AOPR_SRC_1))
        b  = to_ref(api.get_src(src, AOPR_SRC_2))
        hi = api.get_src(src, AOPR_SRC_HI)
        lo = api.get_src(src, AOPR_SRC_LO)

        zero   = val(X_LEN, 0,                "md_zero")
        ones   = val(X_LEN, (1 << X_LEN) - 1, "md_ones")
        a_sign = a[X_LEN - 1]
        b_sign = b[X_LEN - 1]

        # ---- the high words: widen, then the top half of a 64-bit product --
        prod_s = widen(a, a_sign, ones, zero) * widen(b, b_sign, ones, zero)
        prod_u = a.extend(WIDE) * b.extend(WIDE)

        # ---- division on magnitudes, the sign put back afterwards ----------
        a_mag  = mux(a_sign, zero - a, a, name="md_a_mag")
        b_mag  = mux(b_sign, zero - b, b, name="md_b_mag")
        q_mag  = a_mag / b_mag
        r_mag  = a_mag % b_mag
        q_neg  = a_sign ^ b_sign                      # the quotient is negative when the signs differ
        div_q  = mux(q_neg,  zero - q_mag, q_mag, name="md_div_q")
        div_r  = mux(a_sign, zero - r_mag, r_mag, name="md_div_r")   # the remainder takes the dividend's sign
        b_zero = b == 0

        hi_res = wire(X_LEN, "md_hi")
        drive_by_uop(hi_res, src, (
            (U.UOP_MULT,  prod_s[WIDE - 1, X_LEN]),
            (U.UOP_MULTU, prod_u[WIDE - 1, X_LEN]),
            (U.UOP_DIV,   mux(b_zero, a, div_r, name="md_div_hi")),
            (U.UOP_DIVU,  mux(b_zero, a, a % b, name="md_divu_hi")),
            (U.UOP_MTHI,  a),
        ))
        lo_res = wire(X_LEN, "md_lo")
        drive_by_uop(lo_res, src, (
            ((U.UOP_MULT, U.UOP_MULTU), a * b),       # the low word is the same either way
            (U.UOP_DIV,   mux(b_zero, ones, div_q, name="md_div_lo")),
            (U.UOP_DIVU,  mux(b_zero, ones, a / b, name="md_divu_lo")),
            (U.UOP_MTLO,  a),
        ))
        rd_res = wire(X_LEN, "md_rd")
        drive_by_uop(rd_res, src, (
            (U.UOP_MUL,  a * b),
            (U.UOP_MFHI, hi),
            (U.UOP_MFLO, lo),
        ))

        with zif(uop_hit(src, (*U.HILO_WRITERS, U.UOP_MTHI))):
            api.wb_reg(AOPR_DEST_HI, hi_res)
        with zif(uop_hit(src, (*U.HILO_WRITERS, U.UOP_MTLO))):
            api.wb_reg(AOPR_DEST_LO, lo_res)
        with zif(uop_hit(src, (U.UOP_MUL, U.UOP_MFHI, U.UOP_MFLO))):
            api.wb_reg(AOPR_DEST_1, rd_res)
        api.declare_fin(src)
        return None                                  # last stage: no next


def widen(value, sign, ones, zero):
    """`value` as a 2 * X_LEN two's-complement operand: the sign fills the top."""
    fill = mux(sign, ones, zero, name="md_fill")
    return value.extend(WIDE) | (fill.extend(WIDE) << X_LEN)
