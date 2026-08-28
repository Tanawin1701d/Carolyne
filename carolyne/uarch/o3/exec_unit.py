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
# the api transfers the is_spec/spec_tag pair from src to des (the pair
# rides in the body's records; the ENGINE writes it). Each stage's api
# (ExecUnitApiO3, exec_unit_api.py) carries the NEXT stage's arbiter
# itself and proxies declare_*/wb_reg onto the top CORE module.
# NOT here yet: writeback (declare_fin/wb_reg cores), the per-stage kill,
# and who calls build_issue with exec_meta.

from kathryn import *

from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.exec_unit_api import ExecUnitApiO3
from carolyne.uarch.o3.rsv import RsvBase


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

        self.core = None    # the top CPU core module, from connect()

    # --- the stage chain ----------------------------------------------------------
    @flow
    def transfer(self):
        """The unit's pipeline: one pip per stage, the body called inside it.

        - stage 0's src is the station's issued entry (exec_src) — the
          station owns that first register transition; stage k's is
          whatever stage k-1 RETURNED, always a register Karray the body
          writes itself
        - the body places its own transfer (api.zync_with_next_stage)
        - every stage's record lands in self.stage_srcs for debugging:
          [k] is what stage k received, [-1] the last stage's return —
          the writeback record
        - LIMIT: no writeback and no per-stage kill yet — the last stage's
          pip has no exit until declare_fin/wb_reg land
        """
        src = self.rsv.exec_src[0]
        self.stage_srcs = [src]
        for stage_idx in range(self.exec_unit.stage_cnt):
            # the api carries the NEXT stage's arb itself; None on the last
            next_meta = (self.stage_metas[stage_idx + 1]
                         if stage_idx + 1 < self.exec_unit.stage_cnt else None)
            with pip(self.stage_metas[stage_idx]):
                api = ExecUnitApiO3(self.core, stage_idx, next_meta)
                src = self.exec_unit.exec_stage(stage_idx, src, api)
            self.stage_srcs.append(src)




