# CoreO3 — the top CPU core module: every block of the machine, built from
# ONE config and wired in one place.
#
# com_declare builds in DEPENDENCY order, one small builder per subsystem so
# the machine reads as a table of parts:
#
#   _build_reg_arch()    TagGen + RegArchMng — what dispatch books against
#   _build_back_end()    Rob + the commit arbiter; one station + one exec
#                        complex per RsvSpec (the spec's own issue_o3 picks
#                        RsvO3/RsvIOR, its POSITION is the rsv_id a lane names)
#   _build_front_end()   Fetch -> Decode -> Dispatch, and backend_meta
#   _wire_stages()       every connect slot, filled HERE and nowhere else
#
# The PipCon map of the machine: Fetch/Decode/Dispatch own their stage arbs
# (fetch_meta/decode_meta/dispatch_meta), each complex owns its exec-stage
# chain's; the core adds only the two nobody owns — `commit_meta` (the arb
# the ROB's commit pip runs on) and `backend_meta` (the arb dispatch's
# granted transfer runs against).
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
from carolyne.uarch.o3.reg_arch_mng import RegArchMng
from carolyne.uarch.o3.rob import Rob
from carolyne.uarch.o3.rsv_ior import RsvIOR
from carolyne.uarch.o3.rsv_o3 import RsvO3
from carolyne.uarch.o3.tag_gen import TagGen


class CoreO3(Module):
    """The whole core: every block, built from one config, wired once."""

    def __init__(self, config: CPUO3_Config, simple_mem: EasyMem):
        self.config     = config
        self.simple_mem = simple_mem
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
        self.reg_arch_mng = RegArchMng(self.config,
                                       rename_ports=self.config.fe_lanes,
                                       commit_ports=self.config.commit_lanes)

    # --- the back end -----------------------------------------------------------
    def _build_back_end(self):
        """The ROB with its commit arbiter, and one station + one exec
        complex per RsvSpec — named by POSITION (rsv{k}/exu{k}), since the
        position is the rsv_id a dispatch lane names and two specs may
        otherwise read alike."""
        self.rob         = Rob(self.config, self.reg_arch_mng)
        self.commit_meta = PipCon(name="commit")

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
        granted transfer runs against; LIMIT: nothing pips on it yet — the
        backend-acceptance story (what grants a bundle out) is open."""
        self.fetch        = Fetch(self.config, self.simple_mem)
        self.decode       = Decode(self.config)
        self.dispatch     = Dispatch(self.config)
        self.backend_meta = PipCon(name="backend")

    # --- the wiring, all of it in one place -------------------------------------
    def _wire_stages(self):
        """Every stage's connect() called here and nowhere else, so the
        core's topology reads as one table."""
        self.fetch   .connect(self.decode)
        self.decode  .connect(self.fetch, self.dispatch)
        self.dispatch.connect(self.decode      , self.backend_meta,
                              self.reg_arch_mng, self.tag_gen     ,
                              self.rob         , self.rsvs)

    # --- commit -----------------------------------------------------------------
    @flow
    def run_commit(self):
        """The commit stage: the ROB drains into architectural state inside
        the commit arbiter's pip.

        LIMIT: the mispredict is not bound as this arb's reset yet (the
        squash fan-out is undesigned), and nothing calls the stations'
        build_issue with the complexes' exec_meta — open on purpose.
        """
        self.rob.build_commit(self.commit_meta)
