# CoreO3 — the top CPU core module: every block of the machine, built from
# ONE config and wired in one place.
#
# com_declare builds in DEPENDENCY order, one small builder per subsystem so
# the machine reads as a table of parts:
#
#   _build_reg_arch()    TagGen + RegArchMng — what dispatch books against
#   _build_back_end()    Rob + StoreBuf; one IssueLane per RsvSpec — its
#                        station and one exec complex per unit the station
#                        feeds (the spec's own issue_o3 picks RsvO3/RsvIOR,
#                        its POSITION is the rsv_id a dispatch lane names)
#   _build_front_end()   Fetch -> Decode -> Dispatch, and backend_meta
#   _wire_stages()       every connect slot, filled HERE and nowhere else
#
# The PipCon map of the machine: Fetch/Decode/Dispatch own their stage arbs
# (fetch_meta/decode_meta/dispatch_meta), the ROB declares `commit_meta`, each
# complex declares its exec-stage chain's; the core adds only the one nothing
# else declares: `backend_meta`, which dispatch's granted transfer runs against.
#
# MEMORY IS ENVIRONMENT, and the core takes PORTS rather than memories: one
# instruction read port per front-end lane, one data read port and one data
# write port. A machine builds the memories outside and hands the ports in, the
# way the eventual SoC will (the reconfigurable-component story), so the core
# names no memory class at all.

from typing import Sequence

from kathryn import *

from carolyne.uarch.mem.common.mem_port import MemPortRead, MemPortWrite
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.decode import Decode
from carolyne.uarch.o3.dispatch import Dispatch
from carolyne.uarch.o3.fetch import Fetch
from carolyne.uarch.o3.issue_lane import build_issue_lanes
from carolyne.uarch.o3.mpft import Mpft
from carolyne.uarch.o3.reg_arch_mng import RegArchMng
from carolyne.uarch.o3.rob import Rob
from carolyne.uarch.o3.store_buf import StoreBuf
from carolyne.uarch.o3.tag_gen import TagGen


class CoreO3(Module):
    """The whole core: every block, built from one config, wired once."""

    def __init__(self,
                 config           : CPUO3_Config,
                 instr_read_ports : Sequence[MemPortRead],
                 data_read_port   : MemPortRead,
                 data_write_port  : MemPortWrite):
        self.config           = config
        self.instr_read_ports = tuple(instr_read_ports)   # one per fetch lane
        self.data_read_port   = data_read_port            # the one load path
        self.data_write_port  = data_write_port           # the one store path
        self._check_ports()
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

    # --- the front end ----------------------------------------------------------
    def _build_front_end(self):
        """Fetch -> Decode -> Dispatch. `backend_meta` is the arb dispatch's
        granted transfer runs against; no pip masters it (`no_pip_master`),
        so dispatch's zync is granted the moment it wins arbitration —
        acceptance is `ready_to_go`'s AND, already bound on the zync."""
        self.fetch        = Fetch(self.config, self.instr_read_ports)
        self.decode       = Decode(self.config)
        self.dispatch     = Dispatch(self.config)
        self.backend_meta = PipCon(name="backend")
        self.backend_meta.no_pip_master()

    # --- the back end -----------------------------------------------------------
    def _build_back_end(self):
        """The ROB and the store buffer, then one IssueLane per RsvSpec —
        its station and the complexes it issues into (issue_lane.py). Commit
        is the ROB's own flow; the core drives nothing."""
        self.store_buf = StoreBuf(self.config, self.data_write_port)
        self.rob       = Rob     (self.config, self.reg_arch_mng,
                                  self.store_buf)

        self.issue_lanes = build_issue_lanes(self.config)

    # --- the wiring, all of it in one place -------------------------------------
    def _wire_stages(self):
        """Every stage's connect() called here and nowhere else, so the
        core's topology reads as one table."""
        self.fetch   .connect(self.decode)
        self.decode  .connect(self.fetch, self.dispatch)
        self.dispatch.connect(self.decode      , self.backend_meta,
                              self.reg_arch_mng, self.tag_gen     ,
                              self.mpft        , self.rob         ,
                              self.rsvs)
        for lane in self.issue_lanes:
            lane.connect(self)          # its station <-> its complexes

    # --- the back end, read flat ------------------------------------------------
    @property
    def rsvs(self):
        """Every reservation station, in spec order."""
        return tuple(lane.rsv for lane in self.issue_lanes)

    @property
    def exus(self):
        """Every execution complex: each lane's, in unit order."""
        return tuple(exu for lane in self.issue_lanes for exu in lane.execs)

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
          `rob_des_idx_dyn` its ROB entry (carried in the stage record)
        - `dest_renames` is (atomic_operand, phy_idx) per dest slot of the
          branch: that class's RT restores the branch's snapshot and its PRF
          rolls back to just past the branch's own allocation
        - the Arf is untouched on purpose: it holds committed state only
        - LIMIT: dispatch books the Mpft rows, but seeds them with the
          NEWEST open tag instead of the mask of every open tag, so this
          read under-kills: younger speculations survive the squash
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

        # only DESTINATION classes hold rename state. No active guard: decode
        # forces every dest slot of a branch active, so rename allocated for
        # all of them and every class has a pointer to roll back.
        for atm_opr, phy_idx in dest_renames:
            rt  = self.reg_arch_mng.rt (atm_opr.reg_file)
            prf = self.reg_arch_mng.prf(atm_opr.reg_file)
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
          `rob_des_idx_dyn` is carried for the commit-side resolve work to come
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

    # --- the ports this core was handed ------------------------------------------
    def _check_ports(self) -> None:
        """Every port is the kind and the SHAPE this config states.

        A port whose memory was built from other numbers would read a different
        word than the core thinks it asked for, and nothing downstream could
        tell.
        """
        isa = self.config.isa
        if len(self.instr_read_ports) != self.config.fe_lanes:
            raise ValueError(
                f"CoreO3: needs one instruction read port per front-end lane, "
                f"got {len(self.instr_read_ports)} for {self.config.fe_lanes}")
        for lane, port in enumerate(self.instr_read_ports):
            self._check_port(port, MemPortRead, f"instr_read_ports[{lane}]",
                             self.config.instr_mem_idx_width, isa.ilen_bytes * 8)
        self._check_port(self.data_read_port, MemPortRead, "data_read_port",
                         self.config.data_mem_idx_width, isa.dlen_bytes * 8)
        self._check_port(self.data_write_port, MemPortWrite, "data_write_port",
                         self.config.data_mem_idx_width, isa.dlen_bytes * 8)

    @staticmethod
    def _check_port(port, kind, where: str, idx_width: int, data_bits: int) -> None:
        if not isinstance(port, kind):
            raise TypeError(
                f"CoreO3: {where} must be a {kind.__name__}, "
                f"got {type(port).__name__}")
        if port.addr_meta.var_widths != (idx_width,):
            raise ValueError(
                f"CoreO3: {where} addresses {port.addr_meta.var_widths}, the "
                f"config states one region of {idx_width} bits")
        if port.addr_meta.data_bus_bits != data_bits:
            raise ValueError(
                f"CoreO3: {where} moves {port.addr_meta.data_bus_bits} bits, "
                f"the ISA states {data_bits}")
