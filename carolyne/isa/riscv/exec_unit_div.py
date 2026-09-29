# DivExecUnit — the M extension's divides, as a six-stage restoring divider:
# stage 0 takes magnitudes and records the signs, stages 1-4 run eight steps
# each (exec_unit_util's DivState / div_steps), stage 5 puts the signs back,
# answers a zero divisor and writes back. Eight steps are ~9 ns of carry
# chain, so every stage fits a 20 ns clock with room; the combinational
# divider this replaces was 35 ns.

from __future__ import annotations

from ..exec_unit import ExecUnitBase
from ..exec_unit_util import (DIV_STEPS_PER_STAGE, div_results, div_start, div_state_record,
                              div_steps, uop_hit)
from . import uop as U
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2
from .reg import X_LEN
from kathryn import mux
from kathryn.signal import to_ref

STEP_STAGES = X_LEN // DIV_STEPS_PER_STAGE        # 4 stages of 8 steps
STAGE_CNT   = STEP_STAGES + 2                     # + the start and the finish


class DivExecUnit(ExecUnitBase):
    """div / divu / rem / remu, eight restoring steps per stage."""

    def declare_stage_src(self, stage_idx, src, api):
        return div_state_record(f"div_s{stage_idx}", X_LEN,
                                api.next_stage_fields(src, AOPR_DEST_1))

    def exec_stage(self, stage_idx, src, api):
        if stage_idx == 0:
            return self._start_stage(src, api)
        if stage_idx <= STEP_STAGES:
            return self._step_stage(stage_idx, src, api)
        return self._finish_stage(src, api)

    def _start_stage(self, src, api):
        with api.zync_with_next_stage(src) as res:
            a         = to_ref(api.get_src(src, AOPR_SRC_1))
            b         = to_ref(api.get_src(src, AOPR_SRC_2))
            signed_op = uop_hit(src, (U.UOP_DIV, U.UOP_REM))
            res[0]   |= div_start(a, b, signed_op, X_LEN)

    def _step_stage(self, stage_idx, src, api):
        first_bit = X_LEN - 1 - (stage_idx - 1) * DIV_STEPS_PER_STAGE
        with api.zync_with_next_stage(src) as res:
            res[0] |= div_steps(src[0], first_bit, DIV_STEPS_PER_STAGE, X_LEN)

    def _finish_stage(self, src, api):
        quotient, remainder = div_results(src[0], X_LEN)
        result = mux(uop_hit(src, (U.UOP_DIV, U.UOP_DIVU)), quotient, remainder,
                     name="div_result")
        api.wb_reg(AOPR_DEST_1, result)
        api.declare_fin(src)
        return None                                  # last stage: no next
