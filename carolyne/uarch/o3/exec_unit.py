# ExecUnitO3 — the function-unit complex behind ONE reservation station: the
# block that takes the station's issued entry and runs the ISA units'
# exec_stage bodies over it (the natural-Kathryn semantics, isa/exec_unit.py).
#
# One complex per station, because issue is the coupling: a station issues one
# entry per cycle through ONE arbiter — and in THIS VERSION the complex runs
# exactly ONE ISA unit, so the spec's `exec_unit` set must be a single unit
# and a machine gives each unit its own station. A multi-unit complex needs
# per-unit routing after issue; that is a later version.
#
# THE STAGE CHAIN (`transfer`): one pip per stage, stage 0's arbiter BEING
# `exec_meta` — the arb the station's build_issue zyncs against, so a busy
# complex stalls the station. The body is called INSIDE its stage's pip, so
# its scwait/cwhile compose with the stage's arbiter; stage k receives the
# record stage k-1 RETURNED — always a REGISTER Karray the body writes
# itself, carrying everything the later stages need (the station owns the
# first register transition: exec_src) — and the body places its own
# transfer with `with api.zync_with_next_stage(src, des):`, INSIDE which
# the api transfers is_spec / spec_tag / rob_des_idx from src to des (the
# triple rides in the body's records; the ENGINE writes it). Each stage's
# api (ExecUnitApiO3, exec_unit_api.py) carries the NEXT stage's arbiter
# itself and proxies declare_*/wb_reg BACK ONTO THIS COMPLEX — the landing
# stubs below, each raising until its machinery lands.
# NOT here yet: that machinery (writeback, squash/resolve fan-out), the
# per-stage kill, and who calls build_issue with exec_meta.

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.o3.common_field import IS_SPEC, ROB_DES_IDX, SPEC_TAG
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, rsv_type_fields
from carolyne.uarch.o3.exec_unit_api import ExecUnitApiO3
from carolyne.uarch.o3.operand_field import PR_IDX, field_name
from carolyne.uarch.o3.rsv import RsvBase, RsvBypass


class ExecUnitO3(Module):
    """The execution complex one reservation station issues into."""

    def __init__(self,
                 config   : CPUO3_Config,
                 rsv      : RsvBase,
                 rsv_spec : RsvSpec,
                 name     : str = ""):

        if not isinstance(rsv, RsvBase):
            raise TypeError(
                f"ExecUnitO3: rsv must be a reservation station (RsvBase), "
                f"got {type(rsv).__name__}")
        if rsv.rsv_spec is not rsv_spec:
            raise ValueError(
                f"ExecUnitO3 '{rsv_spec.label}': the station was built from a "
                f"DIFFERENT spec ('{rsv.rsv_spec.label}') — the complex and its "
                f"station must read one spec, or their unit sets drift")
        if len(rsv_spec.exec_unit) != 1:
            raise ValueError(
                f"ExecUnitO3 '{rsv_spec.label}': the spec feeds "
                f"{len(rsv_spec.exec_unit)} execution units — this version runs "
                f"ONE unit per station, so give each unit its own station")

        self.config    = config
        self.rsv       = rsv
        self.rsv_spec  = rsv_spec
        # The ONE ISA unit this complex elaborates — this version's bound;
        # a multi-unit complex needs per-unit routing after issue.
        self.exec_unit = rsv_spec.exec_unit[0]
        self.label     = name or f"exu_{rsv_spec.label.replace('/', '_')}"
        # The top core module, from connect(). Underscored: it is a BACK
        # reference, and the sim manifest walks public module attributes —
        # a public ancestor ref would read as an attribute cycle.
        self._core     = None
        # Set by declare_mis_pred / declare_suc_pred: this complex is the
        # fan-out's caller, so on_mis_pred / on_suc_pred exclude it (the
        # declaring branch itself must finish untouched).
        self._declared_mis_pred = False
        self._declared_suc_pred = False

        # A unit's `needs` may name record fields its body reads (pc/npc) —
        # the station KIND is what carries them, so a kind without them
        # would hand the body a field that does not exist.
        kind_fields = {field for field, _ in
                       rsv_type_fields(rsv_spec.rsv_type, config.pc_width)}
        for facility in ("pc", "npc"):
            if facility in self.exec_unit.needs and facility not in kind_fields:
                raise ValueError(
                    f"ExecUnitO3 '{rsv_spec.label}': unit "
                    f"'{self.exec_unit.name}' needs '{facility}', but station "
                    f"kind {rsv_spec.rsv_type.name} carries "
                    f"{sorted(kind_fields) or 'no pc fields'} — pick a kind "
                    f"whose entries have it")

        super().__init__()

    @init
    def com_declare(self):
        # The issue handshake: the arbiter the station's build_issue zyncs
        # against, so a complex that does not take the entry stalls the
        # station rather than dropping it. Who calls build_issue with it,
        # and when, is still open.
        self.exec_meta = PipCon(name=f"{self.label}_exec")

        # One arbiter per stage, stage 0's BEING the issue arb — the station
        # hands the entry straight into the first stage's pip.
        self.stage_metas = [self.exec_meta] + [
            PipCon(name=f"{self.label}_s{stage_idx}")
            for stage_idx in range(1, self.exec_unit.stage_cnt)]


    def connect(self, core):
        """The top core module — where the declare fan-outs land."""
        self._core = core

    # --- what the api's declare_*/wb_reg land on ----------------------------------
    # Loud stubs: a body reaching one today fails at elaboration rather than
    # silently building no hardware; each lands with its machinery.

    def declare_mis_pred(self, src, stage_idx: int, dyn_cond=None):
        """A stage resolved a prediction WRONG under `dyn_cond`: the whole
        core rolls back, keyed by the record this stage carries.

        - `src`'s SPEC_TAG is the branch's own tag, ROB_DES_IDX its entry —
          the two the fan-out needs (the api hands its stage's record in)
        - the zif is what scopes the squash: every flush wire and rollback
          write the core builds takes `dyn_cond` as its gate
        - this complex EXCLUDES ITSELF from the per-stage kill (see
          on_mis_pred): the mispredicting branch is older than everything
          the squash kills, and it still has to finish and report
        - LIMIT: `dest_renames` rides empty — the record cannot say whether
          the branch writes its dest, so no RT/PRF pointer rolls back yet
        """
        if dyn_cond is None:
            raise ValueError(
                f"ExecUnitO3 '{self.label}'.declare_mis_pred: needs the "
                f"mispredict condition — an unconditional squash is nonsense")
        self._declared_mis_pred = True
        with zif(dyn_cond):
            self._core.on_mis_pred(to_ref(getattr(src, SPEC_TAG)),
                                   to_ref(getattr(src, ROB_DES_IDX)))

    def declare_suc_pred(self, src, dyn_cond=None):
        """A stage resolved a prediction CORRECTLY under `dyn_cond`: the tag
        stops covering anything, core-wide (CoreO3.on_suc_pred).

        - `src`'s SPEC_TAG is the branch's own tag, ROB_DES_IDX its entry —
          the api hands its stage's record in, exactly the declare_mis_pred
          shape
        - this complex EXCLUDES ITSELF from the stage mask (see
          on_suc_pred), the declare_mis_pred symmetry
        """
        if dyn_cond is None:
            raise ValueError(
                f"ExecUnitO3 '{self.label}'.declare_suc_pred: needs the "
                f"resolve condition — an unconditional resolve is nonsense")
        self._declared_suc_pred = True
        with zif(dyn_cond):
            self._core.on_suc_pred(to_ref(getattr(src, SPEC_TAG)),
                                   to_ref(getattr(src, ROB_DES_IDX)))

    def declare_fin(self, src, stage_idx: int):
        """A µop finished — report it against the `rob_des_idx` carried in
        `src`, the stage's own record (Rob.on_write_back).

        - built in the caller's scope: the wb_fin write fires on this
          stage's grant, and on any body zif around the call
        """
        self._core.rob.on_write_back(to_ref(getattr(src, ROB_DES_IDX)))

    def wb_reg(self, src, stage_idx: int, atm_opr, value):
        """Write `value` back to that dest slot's promised physical register
        — the class's PRF entry plus the bypass broadcast to every station.

        - `pr_idx` is the stage record's own field for the slot, the index
          rename promised at dispatch
        - the PRF entry takes the value and its `fin`; the broadcast wakes
          every station's waiting sources naming that class
        - respects the enclosing Kathryn scope: a zif-gated call builds
          gated writes, and the broadcast's live bit is driven in that
          same scope, so a gated-out cycle broadcasts nothing
        """

        # TODO we will come back to manage it again

        pr_idx = to_ref(getattr(src, field_name(PR_IDX, atm_opr)))
        self._core.reg_arch_mng.prf(atm_opr.reg_file).on_wb(pr_idx, value)

        wb_live  = wire(1, f"{self.label}_wb_live_s{stage_idx}_{atm_opr.name}")
        wb_live *= val(1, 1)
        bypass = RsvBypass(atm_opr.reg_file, wb_live, pr_idx, value)
        for rsv in self._core.rsvs:
            rsv.on_bypass(bypass)

    # --- the stage chain ----------------------------------------------------------
    @flow
    def transfer(self):
        """The unit's pipeline: one pip per stage, the body called inside it.

        - stage 0's src is the station's issued entry (exec_src) — the
          station owns that first register transition; stage k's is the
          NEW register Karray stage k-1 returned, never src passed on
        - the body places its own transfer (api.zync_with_next_stage);
          the LAST stage returns None — its results leave through
          api.wb_reg — and both conventions are ENFORCED here
        - every stage's record lands in self.stage_srcs for debugging:
          [k] is what stage k received; [-1] is the last stage's None
        """
        src = self.rsv.exec_src[0]
        self.stage_srcs = [src]
        last = self.exec_unit.stage_cnt - 1
        for stage_idx in range(self.exec_unit.stage_cnt):
            # the api carries the NEXT stage's arb itself; None on the last
            next_meta = (self.stage_metas[stage_idx + 1]
                         if stage_idx != last else None)
            with pip(self.stage_metas[stage_idx], auto_restart=True):
                api = ExecUnitApiO3(self, stage_idx, next_meta, src)
                src = self.exec_unit.exec_stage(stage_idx, src, api)
            if stage_idx == last and src is not None:
                raise ValueError(
                    f"ExecUnitO3 '{self.label}': stage {stage_idx} is the LAST "
                    f"of unit '{self.exec_unit.name}' and must return None — "
                    f"results leave through api.wb_reg(atm_opr, value)")
            if stage_idx != last and src is None:
                raise ValueError(
                    f"ExecUnitO3 '{self.label}': stage {stage_idx} of unit "
                    f"'{self.exec_unit.name}' returned None — a stage before "
                    f"the last hands a NEW register record to the next stage")
            self.stage_srcs.append(src)

    # --- mispredict ---------------------------------------------------------------
    def on_mis_pred(self, fix_tag):
        """Kill every in-flight µop speculating under a killed tag, per stage.

        - selective: each stage's arb is flushed inside a zif on THAT
          stage's own record tag, so an older µop the branch never covered
          keeps running
        - stage 0's record is the station's issued entry (exec_src), judged
          by the station's own entry_squashed; later stages carry
          is_spec/spec_tag on the body's records (the api's transfer)
        - clearing the grant is the whole kill: the pip's state IS the
          valid bit, so no writeback fires from a flushed stage
        - call AFTER transfer for a multi-stage unit — the stage records
          only exist once the chain is built
        - the complex that DECLARED the squash returns immediately: the
          mispredicting branch is older than everything the kill covers,
          and it still has to finish and report its fin
        """
        if self._declared_mis_pred:
            return
        for stage_idx, stage_meta in enumerate(self.stage_metas):
            if stage_idx == 0:
                src      = self.rsv.exec_src[0]
                squashed = self.rsv.entry_squashed(src, fix_tag)
            else:
                if not hasattr(self, "stage_srcs"):
                    raise ValueError(
                        f"ExecUnitO3 '{self.label}': on_mis_pred before "
                        f"transfer — stage {stage_idx}'s record does not "
                        f"exist until the stage chain is built")
                src      = self.stage_srcs[stage_idx]
                squashed = (to_ref(getattr(src, IS_SPEC))
                            & ((to_ref(getattr(src, SPEC_TAG)) & fix_tag)
                               != 0))
            with zif(squashed):
                stage_meta.flush()

    def on_suc_pred(self, suc_tag):
        """A prediction resolved correctly: every stage's record stops
        speculating under the resolved tag, the RsvBase mask-out idiom.

        - stage 0's record is the station's exec_src; later stages carry
          IS_SPEC/SPEC_TAG on the body's records (the api's transfer)
        - call AFTER transfer for a multi-stage unit — the stage records
          only exist once the chain is built
        - the complex that DECLARED the resolve returns immediately, the
          on_mis_pred symmetry — the declaring branch's own records stay
          untouched
        - LIMIT: a record hopping stages in the resolve cycle copies its
          tag BEFORE the mask lands (the race on_issue solves with
          substitution) — the api's transfer learns the same substitution
        """
        if self._declared_suc_pred:
            return
        for stage_idx in range(self.exec_unit.stage_cnt):
            if stage_idx == 0:
                src = self.rsv.exec_src[0]
            else:
                if not hasattr(self, "stage_srcs"):
                    raise ValueError(
                        f"ExecUnitO3 '{self.label}': on_suc_pred before "
                        f"transfer — stage {stage_idx}'s record does not "
                        f"exist until the stage chain is built")
                src = self.stage_srcs[stage_idx]
            left = to_ref(getattr(src, SPEC_TAG)) & ~suc_tag
            src |= {SPEC_TAG: left, IS_SPEC: left != 0}




