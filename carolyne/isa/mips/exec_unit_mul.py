# MulExecUnit — the HI/LO accumulator's instructions but the divides, in two
# stages: mult/multu/mul compute their products in stage 0 and REGISTER the
# three result words, stage 1 writes them back. The register keeps the DSP
# cascade off the bypass path into the other stations. mfhi/mflo/mthi/mtlo
# ride the same pipeline: their result is a source moved to a slot.
#
# Kathryn's `*` takes the LEFT operand's width, so the low word is `a * b` on
# the 32-bit operands and the high words come from operands widened to
# 2 * X_LEN first — a signed one by a mux fill.
#
# EVERY writeback is GATED on the µops that write that destination: a µop
# that does not write a slot booked no physical register for it, and an
# unguarded write would land on a garbage pr_idx.

from __future__ import annotations

from kathryn import HwComponentType, Karray, kaf, mux, val, wire, zif
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from ..exec_unit_util import drive_by_uop, uop_hit
from . import uop as U
from .operand import (AOPR_DEST_1, AOPR_DEST_HI, AOPR_DEST_LO, AOPR_SRC_1, AOPR_SRC_2,
                      AOPR_SRC_HI, AOPR_SRC_LO)
from .reg import X_LEN

WIDE = 2 * X_LEN


class MulResult(Karray):
    """Stage 0 -> stage 1: what each destination slot receives."""
    hi_res = kaf()
    lo_res = kaf()
    rd_res = kaf()


class MulExecUnit(ExecUnitBase):
    """mult / multu / mul / mfhi / mflo / mthi / mtlo: compute, then write back."""

    def declare_stage_src(self, stage_idx, src, api):
        return MulResult(HwComponentType.REG, (1,), "mul_res",
                         hi_res=X_LEN, lo_res=X_LEN, rd_res=X_LEN,
                         **api.next_stage_fields(src, AOPR_DEST_1, AOPR_DEST_HI, AOPR_DEST_LO))

    def exec_stage(self, stage_idx, src, api):
        if stage_idx == 0:
            return self._multiply_stage(src, api)
        return self._writeback_stage(src, api)

    def _multiply_stage(self, src, api):
        # everything the transfer reads is computed INSIDE the handshake block
        # (ExecUnitApi.zync_with_next_stage)
        with api.zync_with_next_stage(src) as res:
            a  = to_ref(api.get_src(src, AOPR_SRC_1))
            b  = to_ref(api.get_src(src, AOPR_SRC_2))
            hi = api.get_src(src, AOPR_SRC_HI)
            lo = api.get_src(src, AOPR_SRC_LO)

            zero   = val(X_LEN, 0,                "mul_zero")
            ones   = val(X_LEN, (1 << X_LEN) - 1, "mul_ones")
            prod_s = widen(a, a[X_LEN - 1], ones, zero) * widen(b, b[X_LEN - 1], ones, zero)
            prod_u = a.extend(WIDE) * b.extend(WIDE)

            hi_res = wire(X_LEN, "mul_hi")
            drive_by_uop(hi_res, src, (
                (U.UOP_MULT,  prod_s[WIDE - 1, X_LEN]),
                (U.UOP_MULTU, prod_u[WIDE - 1, X_LEN]),
                (U.UOP_MTHI,  a),
            ))
            lo_res = wire(X_LEN, "mul_lo")
            drive_by_uop(lo_res, src, (
                ((U.UOP_MULT, U.UOP_MULTU), a * b),       # the low word is the same either way
                (U.UOP_MTLO,  a),
            ))
            rd_res = wire(X_LEN, "mul_rd")
            drive_by_uop(rd_res, src, (
                (U.UOP_MUL,  a * b),
                (U.UOP_MFHI, hi),
                (U.UOP_MFLO, lo),
            ))
            res[0] |= {"hi_res": hi_res, "lo_res": lo_res, "rd_res": rd_res}

    def _writeback_stage(self, src, api):
        with zif(uop_hit(src, (U.UOP_MULT, U.UOP_MULTU, U.UOP_MTHI))):
            api.wb_reg(AOPR_DEST_HI, to_ref(src[0].hi_res))
        with zif(uop_hit(src, (U.UOP_MULT, U.UOP_MULTU, U.UOP_MTLO))):
            api.wb_reg(AOPR_DEST_LO, to_ref(src[0].lo_res))
        with zif(uop_hit(src, (U.UOP_MUL, U.UOP_MFHI, U.UOP_MFLO))):
            api.wb_reg(AOPR_DEST_1, to_ref(src[0].rd_res))
        api.declare_fin(src)
        return None                                  # last stage: no next


def widen(value, sign, ones, zero):
    """`value` as a 2 * X_LEN two's-complement operand: the sign fills the top."""
    fill = mux(sign, ones, zero, name="mul_fill")
    return value.extend(WIDE) | (fill.extend(WIDE) << X_LEN)
