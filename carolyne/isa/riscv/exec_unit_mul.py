# MulExecUnit — the M extension's multiplies, in two stages: the products are
# computed and REGISTERED in stage 0, stage 1 picks the word the µop wants and
# writes it back. The register is what keeps the DSP cascade off the bypass
# path into the other stations.
#
# Kathryn's `*` takes the LEFT operand's width, so MUL is `a * b` on the
# 32-bit operands (the low word), and the high words come from operands
# widened to 2 * X_LEN first — a signed operand by the mux fill imm_api uses.

from __future__ import annotations

from kathryn import HwComponentType, Karray, kaf, mux, val, wire
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from ..exec_unit_util import drive_by_uop, uop_hit
from . import uop as U
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2
from .reg import X_LEN

WIDE = 2 * X_LEN


class MulResult(Karray):
    """Stage 0 -> stage 1: the two words a multiply may want."""
    lo = kaf()      # the low word of the product: MUL
    hi = kaf()      # the high word the µop asked for: MULH / MULHSU / MULHU


class MulExecUnit(ExecUnitBase):
    """mul / mulh / mulhsu / mulhu: multiply, then write back."""

    def declare_stage_src(self, stage_idx, src, api):
        return MulResult(HwComponentType.REG, (1,), "mul_res", lo=X_LEN, hi=X_LEN,
                         **api.next_stage_fields(src, AOPR_DEST_1))

    def exec_stage(self, stage_idx, src, api):
        if stage_idx == 0:
            return self._multiply_stage(src, api)
        return self._writeback_stage(src, api)

    def _multiply_stage(self, src, api):
        # everything the transfer reads is computed INSIDE the handshake block
        # (ExecUnitApi.zync_with_next_stage)
        with api.zync_with_next_stage(src) as res:
            a      = to_ref(api.get_src(src, AOPR_SRC_1))
            b      = to_ref(api.get_src(src, AOPR_SRC_2))
            zero   = val(X_LEN, 0,                "mul_zero")
            ones   = val(X_LEN, (1 << X_LEN) - 1, "mul_ones")
            a_sign = a[X_LEN - 1]
            b_sign = b[X_LEN - 1]

            a_signed   = widen(a, a_sign, ones, zero)
            b_signed   = widen(b, b_sign, ones, zero)
            a_unsigned = a.extend(WIDE)
            b_unsigned = b.extend(WIDE)

            hi = wire(X_LEN, "mul_hi")
            drive_by_uop(hi, src, (
                (U.UOP_MULH,   (a_signed   * b_signed  )[WIDE - 1, X_LEN]),
                (U.UOP_MULHSU, (a_signed   * b_unsigned)[WIDE - 1, X_LEN]),
                (U.UOP_MULHU,  (a_unsigned * b_unsigned)[WIDE - 1, X_LEN]),
            ))
            res[0] |= {"lo": a * b, "hi": hi}

    def _writeback_stage(self, src, api):
        result = mux(uop_hit(src, U.UOP_MUL), to_ref(src[0].lo), to_ref(src[0].hi),
                     name="mul_result")
        api.wb_reg(AOPR_DEST_1, result)
        api.declare_fin(src)
        return None                                  # last stage: no next


def widen(value, sign, ones, zero):
    """`value` as a 2 * X_LEN two's-complement operand: the sign fills the top."""
    fill = mux(sign, ones, zero, name="mul_fill")
    return value.extend(WIDE) | (fill.extend(WIDE) << X_LEN)
