# ExecUnitApiO3 — the api a stage body receives from the O3 generator: the
# uarch half of isa/exec_unit_api.py. The declare_*/wb_reg calls PROXY back
# onto the body's OWN EXECUTION-UNIT COMPLEX (ExecUnitO3, exec_unit.py) —
# the complex is what holds the stage records and the connections the
# effects need, and it is the one block that knows which µop the call is
# about. Its landing methods raise until their machinery is built.
#
# zync_with_next_stage is handled LOCALLY: the api carries the NEXT stage's
# arbiter itself, and inside the sync it transfers is_spec / spec_tag /
# rob_des_idx from `src` to `des` — the triple rides in the body's own
# records, but the ENGINE writes it, so a body cannot forget the
# speculation state a squash matches against nor the ROB entry the
# writeback reports to.

from __future__ import annotations

from contextlib import contextmanager

from kathryn import PipCon, zync
from kathryn.signal import to_ref

from carolyne.isa import AtomicOperand, ExecUnitApi
from carolyne.uarch.o3.common_field import IS_SPEC, ROB_DES_IDX, SPEC_TAG


class ExecUnitApiO3(ExecUnitApi):
    """The O3 api a stage body receives: one per stage, proxying back onto
    its own complex and carrying its own next-stage arbiter."""

    def __init__(self, exu, stage_idx: int, pip_con: PipCon | None = None,
                 src=None):
        self.exu       = exu         # the ExecUnitO3 complex this stage is of
        self.stage_idx = stage_idx
        self.pip_con   = pip_con     # the NEXT stage's arb; None on the last
        self.src       = src         # this stage's own record (the declares
                                     # read its tag / rob_des_idx off it)

    def declare_mis_pred(self, dyn_cond=None):
        self.exu.declare_mis_pred(self.src, self.stage_idx, dyn_cond)

    def declare_suc_pred(self, dyn_cond=None):
        self.exu.declare_suc_pred(self.src, dyn_cond)

    @contextmanager
    def zync_with_next_stage(self, src, des):
        """The handshake into the next stage, held in a `with` block.

        - `src` is the record this stage received, `des` the register
          record it hands on — the body's own writes to `des` belong
          INSIDE this block, so they fire on the grant that moves the µop
        - the engine transfers is_spec / spec_tag / rob_des_idx from src
          to des in here, which is why `des` must carry all three
        - the LAST stage has no next: completion is declare_fin/wb_reg's
          business
        """
        if self.pip_con is None:
            raise ValueError(
                f"ExecUnitApiO3: stage {self.stage_idx} is the LAST of its "
                f"unit — there is no next stage to sync with; completion is "
                f"declare_fin/wb_reg's business")
        with zync(self.pip_con):
            des |= {IS_SPEC    : to_ref(getattr(src, IS_SPEC)),
                    SPEC_TAG   : to_ref(getattr(src, SPEC_TAG)),
                    ROB_DES_IDX: to_ref(getattr(src, ROB_DES_IDX))}
            yield

    def declare_fin(self, src):
        self.exu.declare_fin(src, self.stage_idx)

    def wb_reg(self, atm_opr: AtomicOperand, value):
        self.exu.wb_reg(self.src, self.stage_idx, atm_opr, value)
