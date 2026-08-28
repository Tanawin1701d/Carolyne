# ExecUnitApiO3 — the api a stage body receives from the O3 generator: the
# uarch half of isa/exec_unit_api.py. The declare_*/wb_reg calls PROXY onto
# the CORE — the top CPU module that contains every block (rob, prfs, rts,
# stations, the exec complexes), because that is where their effects land: a
# squash fans out core-wide, declare_fin reports to the ROB, wb_reg drives a
# class's PRF port and the bypass. The core's class does not exist yet —
# those forward to the methods it will supply.
#
# zync_with_next_stage is the exception, handled LOCALLY: the api carries
# the NEXT stage's arbiter itself, and inside the sync it transfers the
# is_spec/spec_tag pair from `src` to `des` — the pair rides in the body's
# own records, but the ENGINE writes it, so a body cannot forget the
# speculation state a squash matches against.

from __future__ import annotations

from contextlib import contextmanager

from kathryn import PipCon, zync
from kathryn.signal import to_ref

from carolyne.isa import AtomicOperand, ExecUnitApi


class ExecUnitApiO3(ExecUnitApi):
    """The O3 api a stage body receives: one per stage, proxying onto the
    core and carrying its own next-stage arbiter."""

    def __init__(self, core, stage_idx: int, pip_con: PipCon | None = None):
        self.core      = core        # the top CPU core module, all blocks
        self.stage_idx = stage_idx
        self.pip_con   = pip_con     # the NEXT stage's arb; None on the last

    def declare_mis_pred(self, dyn_cond=None):
        self.core.declare_mis_pred(self.stage_idx, dyn_cond)

    def declare_suc_pred(self, dyn_cond=None):
        self.core.declare_suc_pred(self.stage_idx, dyn_cond)

    @contextmanager
    def zync_with_next_stage(self, src, des):
        """The handshake into the next stage, held in a `with` block.

        - `src` is the record this stage received, `des` the register
          record it hands on — the body's own writes to `des` belong
          INSIDE this block, so they fire on the grant that moves the µop
        - the engine transfers is_spec/spec_tag from src to des in here,
          which is why `des` must carry both fields
        - the LAST stage has no next: completion is declare_fin/wb_reg's
          business
        """
        if self.pip_con is None:
            raise ValueError(
                f"ExecUnitApiO3: stage {self.stage_idx} is the LAST of its "
                f"unit — there is no next stage to sync with; completion is "
                f"declare_fin/wb_reg's business")
        with zync(self.pip_con):
            des |= {"is_spec" : to_ref(src.is_spec),
                    "spec_tag": to_ref(src.spec_tag)}
            yield

    def declare_fin(self):
        self.core.declare_fin(self.stage_idx)

    def wb_reg(self, atm_opr: AtomicOperand):
        self.core.wb_reg(self.stage_idx, atm_opr)
