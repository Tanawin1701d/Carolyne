# The M extension: multiply and divide, in one combinational stage.
#
# Kathryn's `*`, `/` and `%` take the LEFT operand's width, so:
# - MUL is `a * b` on the 32-bit operands (the low word is what it wants);
#   the high words come from operands widened to 2 * X_LEN first, a signed
#   operand by the mux fill imm_api uses (all ones above the sign, or zeros)
# - `/` and `%` are unsigned: DIV / REM go through magnitudes and a sign fix,
#   which also gives INT_MIN / -1 = INT_MIN with remainder 0, as the spec says
# - a divisor of zero is muxed to the spec's values (quotient all ones,
#   remainder the dividend): Verilog would give X
#
# LIMIT: a 32-bit combinational divider bounds fmax until a sequential
# divider replaces it — the station keeps it off the ALUs' path (rv_config.py).
# LIMIT: not yet simulated; the bodies are checked by elaboration.

from __future__ import annotations

from kathryn import mux, val, wire
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from . import uop as U
from .exec_unit_util import drive_by_uop
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2
from .reg import X_LEN

WIDE = 2 * X_LEN


class MulDivExecUnit(ExecUnitBase):
    """mul / mulh / mulhsu / mulhu / div / divu / rem / remu, all in one stage."""

    def exec_stage(self, stage_idx, src, api):
        a = to_ref(api.get_src(src, AOPR_SRC_1))
        b = to_ref(api.get_src(src, AOPR_SRC_2))

        zero   = val(X_LEN, 0,                "md_zero")
        ones   = val(X_LEN, (1 << X_LEN) - 1, "md_ones")
        a_sign = a[X_LEN - 1]
        b_sign = b[X_LEN - 1]

        # ---- the high words: widen, then the top half of a 64-bit product --
        a_signed   = widen(a, a_sign, ones, zero)
        b_signed   = widen(b, b_sign, ones, zero)
        a_unsigned = a.extend(WIDE)
        b_unsigned = b.extend(WIDE)
        mulh   = (a_signed   * b_signed  )[WIDE - 1, X_LEN]
        mulhsu = (a_signed   * b_unsigned)[WIDE - 1, X_LEN]
        mulhu  = (a_unsigned * b_unsigned)[WIDE - 1, X_LEN]

        # ---- division on magnitudes, the sign put back afterwards ----------
        a_mag  = mux(a_sign, zero - a, a, name="md_a_mag")
        b_mag  = mux(b_sign, zero - b, b, name="md_b_mag")
        q_mag  = a_mag / b_mag
        r_mag  = a_mag % b_mag
        q_neg  = a_sign ^ b_sign                     # the quotient is negative when the signs differ
        div    = mux(q_neg,  zero - q_mag, q_mag, name="md_div")
        rem    = mux(a_sign, zero - r_mag, r_mag, name="md_rem")   # the remainder takes the dividend's sign
        b_zero = b == 0

        result = wire(X_LEN, "muldiv_result")
        drive_by_uop(result, src, (
            (U.UOP_MUL,    a * b),
            (U.UOP_MULH,   mulh),
            (U.UOP_MULHSU, mulhsu),
            (U.UOP_MULHU,  mulhu),
            (U.UOP_DIV,    mux(b_zero, ones, div,   name="md_div_out")),
            (U.UOP_DIVU,   mux(b_zero, ones, a / b, name="md_divu_out")),
            (U.UOP_REM,    mux(b_zero, a,    rem,   name="md_rem_out")),
            (U.UOP_REMU,   mux(b_zero, a,    a % b, name="md_remu_out")),
        ))

        api.wb_reg(AOPR_DEST_1, result)
        api.declare_fin(src)
        return None                                  # last stage: no next


def widen(value, sign, ones, zero):
    """`value` as a 2 * X_LEN two's-complement operand: the sign fills the top."""
    fill = mux(sign, ones, zero, name="md_fill")
    return value.extend(WIDE) | (fill.extend(WIDE) << X_LEN)
