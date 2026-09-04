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

from kathryn import PipCon, kaf, priority, zync
from kathryn.signal import to_ref

from carolyne.isa import AtomicOperand, ExecUnitApi
from carolyne.uarch.o3.common_field import (IS_SPEC, ROB_DES_IDX, SPEC_TAG,
                                            UOP_IDX)
from carolyne.uarch.o3.operand_field import PR_IDX, field_name
from carolyne.uarch.o3.priority import PRI_ISSUE


class ExecUnitApiO3(ExecUnitApi):
    """The O3 api a stage body receives: one per stage, proxying back onto
    its own complex and carrying its own next-stage arbiter."""

    # What zync_with_next_stage moves from src to des. The speculation pair
    # and the ROB entry always; next_stage_fields WIDENS it to everything it
    # declared, so a field the engine adds is a field the engine carries.
    _carried = (IS_SPEC, SPEC_TAG, ROB_DES_IDX)

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
    def zync_with_next_stage(self, src, des, cond=None):
        """The handshake into the next stage, held in a `with` block.

        - `src` is the record this stage received, `des` the register
          record it hands on — the body's own writes to `des` belong
          INSIDE this block, so they fire on the grant that moves the µop
        - the engine transfers its OWN fields from src to des in here —
          `_carried`, which next_stage_fields widens to everything it
          declared, so `des` must carry each of them
        - `cond` gates the handshake: the (PipCon, cond) bind the station
          issue already uses, so the µop STALLS here while it is low
        - the LAST stage has no next: completion is declare_fin/wb_reg's
          business
        """
        if self.pip_con is None:
            raise ValueError(
                f"ExecUnitApiO3: stage {self.stage_idx} is the LAST of its "
                f"unit — there is no next stage to sync with; completion is "
                f"declare_fin/wb_reg's business")
        bind = self.pip_con if cond is None else (self.pip_con, cond)
        with zync(bind):
            # At PRI_ISSUE, and the body's writes with it: a record LANDING in
            # a stage must beat on_suc_pred's mask, which is computed from
            # that stage record's PREVIOUS contents. Same rung, same reason,
            # as the station's copy into exec_src.
            with priority(PRI_ISSUE):
                # The speculation pair goes through the complex's
                # spec_overrider: on_suc_pred masks it there, so a tag
                # resolving in this cycle never reaches `des`. Everything
                # else copies straight across — only the pair can go stale.
                spec_ovr = self.exu.spec_overriders[self.stage_idx][0]
                spec_ovr *= {IS_SPEC : to_ref(getattr(src[0], IS_SPEC)),
                             SPEC_TAG: to_ref(getattr(src[0], SPEC_TAG))}

                des[0] |= {
                    name: to_ref(getattr(
                        self.exu.spec_overriders[self.stage_idx][0]
                        if name in (IS_SPEC, SPEC_TAG) else src[0], name))
                    for name in self._carried}
                yield

    def next_stage_fields(self, src, *dest_oprs: AtomicOperand) -> dict:
        """The machine's fields for the body's next-stage record — the
        record vocabulary this generator owns, sized off `src`.

        - the speculation pair (a squash matches on it), the ROB entry
          (declare_fin reports against it), the µop kind (uop_hit reads
          it), plus each named dest's promised register (wb_reg writes
          through it)
        - a Karray keyword whose value is a `kaf()` ADDS that field to
          this array alone, which is why a body's class body need not
          declare any of them
        - widens `_carried`, so zync_with_next_stage moves exactly the
          set declared here
        """
        fields = {name: kaf(self.field_width(src, name))
                  for name in (IS_SPEC, SPEC_TAG, ROB_DES_IDX, UOP_IDX)}
        for atm_opr in dest_oprs:
            if not atm_opr.is_dest:
                raise ValueError(
                    f"ExecUnitApiO3.next_stage_fields: operand "
                    f"'{atm_opr.name}' is a {atm_opr.role} — only a DEST "
                    f"slot promises a physical register")
            name         = field_name(PR_IDX, atm_opr)
            fields[name] = kaf(self.field_width(src, name))
        self._carried = tuple(fields)
        return fields

    def declare_fin(self, src):
        self.exu.declare_fin(src, self.stage_idx)

    def wb_reg(self, atm_opr: AtomicOperand, value):
        self.exu.wb_reg(self.src, self.stage_idx, atm_opr, value)

    # --- the load/store queue -------------------------------------------------
    def lsq_is_full(self):
        return self.exu.lsq_is_full()

    def lsq_push_store(self, mem_addr, data):
        self.exu.lsq_push_store(self.src, mem_addr, data)

    def lsq_search(self, mem_addr):
        return self.exu.lsq_search(mem_addr)

    def mem_read(self, mem_addr):
        return self.exu.mem_read(mem_addr)
