# CoreO3 — the top CPU core module: every block of the machine, built from
# ONE config and wired in one place.
#
# com_declare builds in DEPENDENCY order, one small builder per subsystem so
# the machine reads as a table of parts:
#
#   _build_reg_arch()    TagGen + RegArchMng — what dispatch books against
#   _build_back_end()    Rob + StoreBuf; one station + one exec
#                        complex per RsvSpec (the spec's own issue_o3 picks
#                        RsvO3/RsvIOR, its POSITION is the rsv_id a lane names)
#   _build_front_end()   Fetch -> Decode -> Dispatch, and backend_meta
#   _wire_stages()       every connect slot, filled HERE and nowhere else
#
# The PipCon map of the machine: Fetch/Decode/Dispatch own their stage arbs
# (fetch_meta/decode_meta/dispatch_meta), the ROB owns `commit_meta`, each
# complex owns its exec-stage chain's; the core adds only the one nobody
# owns — `backend_meta` (the arb dispatch's granted transfer runs against).
#
# The instruction memory is ENVIRONMENT, not the core's: a machine hands it
# in, the way the eventual SoC will (the reconfigurable-component story).

from kathryn import *

from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.decode import Decode
from carolyne.uarch.o3.dispatch import Dispatch
from carolyne.uarch.o3.easy_mem import EasyMem
from carolyne.uarch.o3.exec_unit import ExecUnitO3
from carolyne.uarch.o3.fetch import Fetch
from carolyne.uarch.o3.mpft import Mpft
from carolyne.uarch.o3.reg_arch_mng import RegArchMng
from carolyne.uarch.o3.rob import Rob
from carolyne.uarch.o3.rsv_ior import RsvIOR
from carolyne.uarch.o3.rsv_o3 import RsvO3
from carolyne.uarch.o3.store_buf import StoreBuf
from carolyne.uarch.o3.tag_gen import TagGen


class CoreO3(Module):
    """The whole core: every block, built from one config, wired once."""

    def __init__(self,
                 config    : CPUO3_Config,
                 instr_mem : EasyMem,
                 data_mem  : EasyMem):
        self.config          = config
        self.instr_mem       = instr_mem     # both memories are ENVIRONMENT:
        self.data_mem        = data_mem      # a machine hands them in
        self._mis_pred_built = False         # on_mis_pred is build-once (arb resets)
        self._suc_pred_built = False         # on_suc_pred too (the hold is set-once)
        super().__init__()

    @init
    def com_declare(self):
        self._build_reg_arch()
        self._build_back_end()
        self._build_front_end()
        self._wire_stages()

    # --- rename's bookkeepers ---------------------------------------------------
    def _build_reg_arch(self):
        """TagGen and the per-class Arf/Prf/Rt set. Port counts: every
        front-end lane may rename in a cycle, every commit lane may retire."""
        self.tag_gen      = TagGen(self.config,
                                   rename_ports=self.config.fe_lanes)
        self.mpft         = Mpft(self.config,
                                 rename_ports=self.config.fe_lanes)
        self.reg_arch_mng = RegArchMng(self.config,
                                       rename_ports=self.config.fe_lanes,
                                       commit_ports=self.config.commit_lanes)

    # --- the back end -----------------------------------------------------------
    def _build_back_end(self):
        """The ROB and the store buffer, and one station + one exec complex
        per RsvSpec — named by POSITION (rsv{k}/exu{k}), since the position
        is the rsv_id a dispatch lane names and two specs may otherwise
        read alike. Commit is the ROB's own flow; the core drives nothing."""
        self.store_buf = StoreBuf(self.config, self.data_mem)
        self.rob       = Rob     (self.config, self.reg_arch_mng,
                                  self.store_buf)

        rsvs, exus = [], []
        for rsv_idx, rsv_spec in enumerate(self.config.rsv_specs):
            station_cls = RsvO3 if rsv_spec.issue_o3 else RsvIOR
            rsv = station_cls(self.config, rsv_spec, f"rsv{rsv_idx}", rsv_idx)
            rsvs.append(rsv)
            exus.append(ExecUnitO3(self.config, rsv, rsv_spec,
                                   f"exu{rsv_idx}"))
        self.rsvs = tuple(rsvs)
        self.exus = tuple(exus)

    # --- the front end ----------------------------------------------------------
    def _build_front_end(self):
        """Fetch -> Decode -> Dispatch. `backend_meta` is the arb dispatch's
        granted transfer runs against; no pip masters it (`no_pip_master`),
        so dispatch's zync is granted the moment it wins arbitration —
        acceptance is `ready_to_go`'s AND, already bound on the zync."""
        self.fetch        = Fetch(self.config, self.instr_mem)
        self.decode       = Decode(self.config)
        self.dispatch     = Dispatch(self.config)
        self.backend_meta = PipCon(name="backend")
        self.backend_meta.no_pip_master()

    # --- the wiring, all of it in one place -------------------------------------
    def _wire_stages(self):
        """Every stage's connect() called here and nowhere else, so the
        core's topology reads as one table."""
        self.fetch   .connect(self.decode)
        self.decode  .connect(self.fetch, self.dispatch)
        self.dispatch.connect(self.decode      , self.backend_meta,
                              self.reg_arch_mng, self.tag_gen     ,
                              self.rob         , self.rsvs)
        # Station <-> complex, by position: the complex reaches the core for
        # the declare fan-outs, the station takes the arb its issue zyncs on.
        for rsv, exu in zip(self.rsvs, self.exus):
            exu.connect(self)               # declare fan-outs land core-wide
            rsv.connect(exu.exec_meta)      # a busy unit stalls the station

    # --- mispredict -------------------------------------------------------------
    def on_mis_pred(self, last_valid_spec_tag_dyn, rob_des_idx_dyn,
                    dest_renames=()):
        """CALL ONCE — the squash fan-out: one call rolls the whole core back.

        - ONCE per elaboration, enforced below: an arb reset is set-once,
          so all conditions that ever squash must be OR-ed by the one
          caller; a second call raises
        - the BRANCH EXECUTION UNIT is that caller, inside a zif on its own
          mispredict condition — every flush wire and write here takes that
          guard as its gate
        - `last_valid_spec_tag_dyn` is the branch's one-hot tag,
          `rob_des_idx_dyn` its ROB entry (rides the stage record)
        - `dest_renames` is (active, atomic_operand, phy_idx) per dest slot
          of the branch: under its active bit that class's RT restores the
          branch's snapshot and its PRF rolls back to just past the
          branch's own allocation
        - the Arf is untouched on purpose: it holds committed state only
        - LIMIT: mpft booking (on_book_rename/on_rename) is unwired — it
          needs the open-tag mask nobody owns yet; the consult reads an
          unbooked table until that lands
        - LIMIT: a branch with no active dest (a plain BEQ) restores no RT
          and rolls no PRF pointer back, so squashed youngers' renames of
          that class survive until a per-tag snapshot exists
        """
        if self._mis_pred_built:
            raise ValueError(
                "CoreO3.on_mis_pred: already built — an arb reset is "
                "set-once, so the one caller ORs every squash condition")
        self._mis_pred_built = True

        fix_tag = self.mpft.get_fix_tag(last_valid_spec_tag_dyn)

        # nothing moves in a squashed cycle: each stage flushes its own arb
        # (the commit arb is the ROB's, flushed in rob.on_mis_pred below)
        self.fetch   .on_mis_pred()
        self.decode  .on_mis_pred()
        self.dispatch.on_mis_pred()

        # every entry and in-flight µop under a killed tag goes away — a
        # buffered speculative store with it
        for rsv in self.rsvs:
            rsv.on_mis_pred(fix_tag)
        for exu in self.exus:
            exu.on_mis_pred(fix_tag)
        self.store_buf.on_mis_pred(fix_tag)

        # the bookkeepers roll back to the branch
        self.tag_gen.on_mis_pred(last_valid_spec_tag_dyn)
        self.mpft   .on_mis_pred(last_valid_spec_tag_dyn)
        self.rob    .on_mis_pred(rob_des_idx_dyn)

        # only DESTINATION classes hold rename state: each dest slot of the
        # branch rolls its class's RT and PRF back, under its active bit
        for active, atm_opr, phy_idx in dest_renames:
            rt  = self.reg_arch_mng.rt (atm_opr.reg_file)
            prf = self.reg_arch_mng.prf(atm_opr.reg_file)
            with zif(active):
                rt .on_mis_pred(last_valid_spec_tag_dyn)
                prf.on_mis_pred(phy_idx)

    # --- resolve ----------------------------------------------------------------
    def on_suc_pred(self, last_valid_spec_tag_dyn, rob_des_idx_dyn):
        """CALL ONCE — the resolve fan-out: the tag stops covering anything.

        - ONCE per elaboration, enforced below: the dispatch hold is
          set-once, so the one caller ORs every resolve condition
        - the BRANCH EXECUTION UNIT is that caller, inside a zif on its own
          correct-prediction condition — every write here takes that guard
        - `last_valid_spec_tag_dyn` is the resolved branch's one-hot tag;
          `rob_des_idx_dyn` rides for the commit-side resolve work to come
          (predictor update) — nothing in the ROB masks today, its entries
          carry no spec tag
        - RT and PRF keep everything: a confirmed speculation IS the
          architectural path, and the tag's snapshot dies when TagGen
          rebooks it
        """
        if self._suc_pred_built:
            raise ValueError(
                "CoreO3.on_suc_pred: already built — the dispatch hold is "
                "set-once, so the one caller ORs every resolve condition")
        self._suc_pred_built = True

        # a booking never lands beside a resolve: dispatch stalls the cycle
        self.dispatch.on_suc_pred()

        # every waiting entry and in-flight µop stops speculating under it —
        # a buffered store with them
        for rsv in self.rsvs:
            rsv.on_suc_pred(last_valid_spec_tag_dyn)
        for exu in self.exus:
            exu.on_suc_pred(last_valid_spec_tag_dyn)
        self.store_buf.on_suc_pred(last_valid_spec_tag_dyn)

        # the bookkeepers: the tag goes back to the pool and off the table
        self.tag_gen.on_suc_pred(val(1, 1))
        self.mpft   .on_suc_pred(last_valid_spec_tag_dyn)
