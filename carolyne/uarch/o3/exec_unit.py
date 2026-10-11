# ExecUnitO3: the execution complex behind one reservation station. It takes
# the station's issued entry and runs one ISA unit's exec_stage bodies on it.
#
#   station ─ exec_src ─> stage 0 ─ zync ─> stage 1 ─ zync ─> ... ─> last stage
#                         pip(exec_meta)    pip(s1)                  wb_reg, declare_fin
#
# - one complex per unit of a station: `unit_idx` picks the unit, the issue
#   slot it reads (rsv.exec_src[unit_idx]) and the arb it gives rsv.connect
# - stage 0's arb IS exec_meta, the one the station zyncs on: a busy complex
#   stalls the station
# - a body gets an api per stage (exec_unit_api.py); its declare_* and wb_reg
#   calls land on this complex
#
# | part              | file                  |
# | ----------------- | --------------------- |
# | stored resolution | exec_unit_resolve.py  |
# | the body's api    | exec_unit_api.py      |

from kathryn        import *
from kathryn.signal import to_ref

from carolyne.debug.sim                  import BranchResolveProbe, KarrayProbe, PipStatusProbe
from carolyne.uarch.o3.bp.bp_base        import BpOutcome
from carolyne.uarch.o3.bp.bp_helper      import bp_field_names
from carolyne.uarch.o3.common_field      import IS_SPEC, NPC, PC, ROB_DES_IDX, SPEC_TAG, SpecLane
from carolyne.uarch.o3.config            import CPUO3_Config, RsvSpec, rsv_type_fields
from carolyne.uarch.o3.exec_unit_api     import ExecUnitApiO3
from carolyne.uarch.o3.exec_unit_resolve import BranchResolve
from carolyne.uarch.o3.operand_field     import PR_IDX, field_name
from carolyne.uarch.o3.priority          import PRI_SUC_PRED
from carolyne.uarch.o3.rsv               import RsvBase, RsvBypass
from carolyne.uarch.o3.rsv_helper        import station_atm_operands


class ExecUnitO3(Module):
    """The execution complex one reservation station issues into."""

    def __init__(self,
                 config   : CPUO3_Config,
                 rsv      : RsvBase,
                 rsv_spec : RsvSpec,
                 unit_idx : int = 0,
                 name     : str = ""):

        if not isinstance(rsv, RsvBase):
            raise TypeError(
                f"ExecUnitO3: rsv must be a reservation station (RsvBase), "
                f"got {type(rsv).__name__}")
        if rsv.rsv_spec is not rsv_spec:
            raise ValueError(
                f"ExecUnitO3 '{rsv_spec.label}': the station was built from a "
                f"different spec ('{rsv.rsv_spec.label}'); the complex and its "
                f"station must read one spec, or their unit sets disagree")
        if not 0 <= unit_idx < len(rsv_spec.exec_unit):
            raise ValueError(
                f"ExecUnitO3 '{rsv_spec.label}': unit_idx {unit_idx} names no "
                f"unit of a station feeding {len(rsv_spec.exec_unit)}")

        self.config    = config
        self.rsv       = rsv
        self.rsv_spec  = rsv_spec
        self.unit_idx  = unit_idx
        self.exec_unit = rsv_spec.exec_unit[unit_idx]
        self.label     = name or f"exu_{rsv_spec.label.replace('/', '_')}_{unit_idx}"
        # the dest slots a squash rolls back; the station's set, since only
        # those have a field in the record
        self.arch_dest_atm_oprs = tuple(
            atm_opr for atm_opr in station_atm_operands(config.isa, rsv_spec)
            if atm_opr.is_dest and atm_opr.has_arch)
        self._core    = None   # from connect(); underscored: the manifest walks public attributes
        self._resolve = None   # BranchResolve, built by the first declare

        # a unit needing pc/npc must sit on a station kind whose entries carry them
        kind_fields = {field for field, _ in rsv_type_fields(rsv_spec.rsv_type, config.pc_width)}
        for facility in (PC, NPC):
            if facility in self.exec_unit.needs and facility not in kind_fields:
                raise ValueError(
                    f"ExecUnitO3 '{rsv_spec.label}': unit '{self.exec_unit.name}' "
                    f"needs '{facility}', but station kind {rsv_spec.rsv_type.name} "
                    f"carries {sorted(kind_fields) or 'no pc fields'}")

        super().__init__()

    @init
    def com_declare(self):
        # one arb per stage; stage 0's is the issue arb the station zyncs on
        self.exec_meta   = PipCon(name=f"{self.label}_exec")
        self.stage_metas = [self.exec_meta] + [
            PipCon(name=f"{self.label}_s{stage_idx}")
            for stage_idx in range(1, self.exec_unit.stage_cnt)]

        # one per stage hop: the speculation pair on its way into the next
        # stage, where on_suc_pred can still clear it before the edge
        self.spec_overriders = [
            SpecLane(HwComponentType.WIRE, (1,), f"{self.label}_spec_ovr{stage_idx}",
                     spec_tag=self.config.sptag_len)
            for stage_idx in range(self.exec_unit.stage_cnt - 1)]

        self._declare_stage_chain()

    def _declare_stage_chain(self):
        """Every stage's record and api, built before any flow block.

            stage_srcs  [exec_src,  s1 record,  s2 record]     s1.. come from the unit
            stage_apis  [api0,      api1,       api2     ]     api k: next arb k+1, src k, des k+1

        - the records live here, not on the unit: one unit may back two complexes
        - transfer reuses these apis: next_stage_fields widens what the same
          api later carries
        """
        last = self.exec_unit.stage_cnt - 1
        self.stage_srcs = [self.rsv.exec_src[self.unit_idx]]
        self.stage_apis = []
        for stage_idx in range(self.exec_unit.stage_cnt):
            next_meta = self.stage_metas[stage_idx + 1] if stage_idx != last else None
            api       = ExecUnitApiO3(self, stage_idx, next_meta, self.stage_srcs[stage_idx])
            self.stage_apis.append(api)
            if stage_idx == last:
                break
            des = self.exec_unit.declare_stage_src(stage_idx + 1, self.stage_srcs[stage_idx], api)
            if not isinstance(des, Karray):
                raise ValueError(
                    f"ExecUnitO3 '{self.label}': declare_stage_src({stage_idx + 1}) of unit "
                    f"'{self.exec_unit.name}' returned {type(des).__name__}; a stage "
                    f"record is a register Karray")
            if des is self.stage_srcs[stage_idx]:
                raise ValueError(
                    f"ExecUnitO3 '{self.label}': declare_stage_src({stage_idx + 1}) of unit "
                    f"'{self.exec_unit.name}' returned the previous stage's record; "
                    f"each stage holds its own")
            api.des = des
            self.stage_srcs.append(des)

    def connect(self, core):
        """The top core module, where the declare fan-outs land."""
        self._core = core

    # ---- what the api's declare_* and wb_reg land on ------------------------------

    def declare_mis_pred(self, src, stage_idx: int, dyn_cond=None, next_pc=None):
        """A branch resolved wrong under `dyn_cond`: the core rolls back one
        cycle later and fetch restarts at `next_pc` (BranchResolve)."""
        if dyn_cond is None:
            raise ValueError(f"ExecUnitO3 '{self.label}'.declare_mis_pred: needs the "
                             f"mispredict condition")
        if next_pc is None:
            raise ValueError(f"ExecUnitO3 '{self.label}'.declare_mis_pred: needs the pc "
                             f"execution continues at, or fetch stays on the wrong path")
        self._branch_resolve(src).store_mis_pred(dyn_cond, next_pc)

    def declare_suc_pred(self, src, dyn_cond=None):
        """A branch resolved right under `dyn_cond`: one cycle later its tag
        stops covering anything (CoreO3.on_suc_pred)."""
        if dyn_cond is None:
            raise ValueError(f"ExecUnitO3 '{self.label}'.declare_suc_pred: needs the "
                             f"resolve condition")
        self._branch_resolve(src).store_suc_pred(dyn_cond)

    def _branch_resolve(self, src) -> BranchResolve:
        if self._resolve is None:
            self._resolve = BranchResolve(self.config, self.label, src, self.arch_dest_atm_oprs)
        return self._resolve

    def declare_br_outcome(self, src, taken, target):
        """A branch resolved: the predictor learns (pc, taken, target) and the
        bp record the branch station carried.

        - LIMIT: pc and the record are read off `src`, so this works on
          stage 0 of an RSV_BRANCH station only
        """
        missing = [name for name in (PC, *bp_field_names(self.config))
                   if not hasattr(src[0], name)]
        if missing:
            raise ValueError(
                f"ExecUnitO3 '{self.label}'.declare_br_outcome: the stage record "
                f"has no {', '.join(missing)}; declare the outcome on stage 0 of "
                f"an RSV_BRANCH station")
        meta = {name: to_ref(getattr(src[0], name)) for name in bp_field_names(self.config)}
        self._core.bp.on_resolve(BpOutcome(to_ref(getattr(src[0], PC)),
                                           to_ref(taken), to_ref(target), meta))

    def declare_fin(self, src, stage_idx: int):
        """A µop finished: report it to its ROB entry."""
        self._core.rob.on_write_back(to_ref(getattr(src[0], ROB_DES_IDX)))

    def wb_reg(self, src, stage_idx: int, atm_opr, value):
        """Write `value` to the dest's promised register and bypass it to every
        station; the enclosing scope gates both."""
        pr_idx = to_ref(getattr(src[0], field_name(PR_IDX, atm_opr)))
        self._core.reg_arch_mng.prf(atm_opr.reg_file).on_wb(pr_idx, value)

        bypass = RsvBypass(atm_opr.reg_file, pr_idx, value)
        for rsv in self._core.rsvs:
            rsv.on_bypass(bypass)

    # ---- the load/store queue and the data memory ----------------------------------

    def lsq_is_full(self):
        return self._core.store_buf.is_full()

    def lsq_push_open(self):
        """1 when the store buffer takes a push this cycle; 0 in a squash cycle."""
        return self._core.store_buf.push_open

    def mem_index(self, mem_addr_wo_static_bit):
        """A body's word address cut to the data memory's index width (a slice)."""
        width = self._core.data_read_port.addr_meta.total_var_width
        return to_ref(mem_addr_wo_static_bit)[width - 1, 0]

    def lsq_push_store(self, src, mem_addr_wo_static_bit, data):
        # the speculation pair comes from the record, so a body cannot forget it
        self._core.store_buf.on_new_entry(to_ref(getattr(src[0], IS_SPEC)),
                                          to_ref(getattr(src[0], SPEC_TAG)),
                                          self.mem_index(mem_addr_wo_static_bit),
                                          data)

    def lsq_search(self, mem_addr_wo_static_bit):
        return self._core.store_buf.search_newest(self.mem_index(mem_addr_wo_static_bit))

    def mem_read_request(self, mem_addr_wo_static_bit):
        # the ask fires in the body's scope, so a stalled stage keeps its address
        port = self._core.data_read_port
        port.bind_addr(self.mem_index(mem_addr_wo_static_bit))
        port.ask()

    def mem_read_data(self):
        # the word the last ask named, one cycle later
        return self._core.data_read_port.read()

    # ---- the stage chain -------------------------------------------------------------

    @flow
    def transfer(self):
        """One pip per stage with the unit's body inside, then the stored
        branch resolution, outside every stage.

        - a stage writes the next record through api.zync_with_next_stage and
          returns None; anything else is refused
        """
        for stage_idx in range(self.exec_unit.stage_cnt):
            with pip(self.stage_metas[stage_idx], auto_restart=True):
                returned = self.exec_unit.exec_stage(stage_idx,
                                                     self.stage_srcs[stage_idx],
                                                     self.stage_apis[stage_idx])
            if returned is not None:
                raise ValueError(
                    f"ExecUnitO3 '{self.label}': stage {stage_idx} of unit "
                    f"'{self.exec_unit.name}' returned a record; a stage writes the "
                    f"next one (api.zync_with_next_stage) and returns None")
        if self._resolve is not None:
            self._resolve.fire(self._core)

    # ---- speculation -------------------------------------------------------------------

    def on_mis_pred(self, fix_tag):
        """Kill every in-flight µop under a killed tag, stage by stage.

            stage k:  zif(record k is_spec & (spec_tag & fix_tag) != 0)  ─>  flush arb k

        - an older µop the branch never covered keeps running
        - flushing the arb is the whole kill: the pip's state is the valid bit
        """
        for stage_idx, stage_meta in enumerate(self.stage_metas):
            if stage_idx == 0:
                src      = self.rsv.exec_src[self.unit_idx][0]
                squashed = self.rsv.entry_squashed(src, fix_tag)
            else:
                src      = self.stage_srcs[stage_idx][0]
                squashed = (to_ref(getattr(src, IS_SPEC))
                            & ((to_ref(getattr(src, SPEC_TAG)) & fix_tag) != 0))
            with zif(squashed):
                stage_meta.flush()

    def on_suc_pred(self, suc_tag):
        """A branch resolved right: clear its tag from every stage record.

            stage hop k:  spec_ovr k   = 0   (the pair moving this cycle)
            stage k:      record k     = 0   (the pair already there)

        - `suc_tag` is one-hot, so the test is `spec_tag == suc_tag`
        - LIMIT: a record hopping stages in this cycle copies its tag before
          the clear lands
        """
        # the guard reads the stage record, never the overrider it drives
        for stage_idx, spec_ovr in enumerate(self.spec_overriders):
            src_row = self.stage_srcs[stage_idx][0]
            with priority(PRI_SUC_PRED):
                with zif(getattr(src_row, IS_SPEC) & (getattr(src_row, SPEC_TAG) == suc_tag)):
                    spec_ovr[0] *= {IS_SPEC: 0, SPEC_TAG: 0}

        for stage_idx in range(self.exec_unit.stage_cnt):
            src = self.stage_srcs[stage_idx][0]
            with zif(getattr(src, IS_SPEC) & (getattr(src, SPEC_TAG) == suc_tag)):
                src |= {SPEC_TAG: 0, IS_SPEC: 0}

    @dbg
    def dbg_probes(self):
        self.dbg_stage_metas = [PipStatusProbe(meta) for meta in self.stage_metas]   # [0] is the issue arb
        self.dbg_stage_srcs  = [KarrayProbe(src) for src in self.stage_srcs[1:]]    # stage 0 is the station's
        resolve = self._resolve
        self.dbg_resolve = BranchResolveProbe(
            resolve.mis_pend    if resolve and resolve.has_mis else None,
            resolve.redirect_pc if resolve and resolve.has_mis else None,
            resolve.suc_pend    if resolve and resolve.has_suc else None)
