# Fetch — one instruction word per front-end lane, per cycle.
#
# ONE READ PORT PER LANE, built by the machine outside the core. A port names
# its BANK as part of the address, so this stage states a byte address and the
# memory routes it — nothing here knows how the memory is banked.
#
#         lane           0        1        2        3
#         word        0x04     0x08     0x0c     0x10   = pc + lane * ilen
#
# That is what lets the pc be ANY aligned address: a lane crossing into the
# next group is a larger address, not a special case.
#
# A lane is valid only if the memory answered it and every lower one, and the
# pc advances by the valid count — so a bank the memory could not serve costs
# fetch bandwidth and never skips an instruction.
#
# THE BRANCH PREDICTOR (bp/) is asked for every lane's next pc in the same
# cycle. Each row stores the prediction (`npc`, the bp_* record). When the
# predictor may say "taken", the group also ends at the first kept lane
# predicted taken, and the pc goes to that lane's npc. A never-taken predictor
# (FallThroughBp) builds neither.

from typing import Sequence

from kathryn           import *
from carolyne.debug.sim import KarrayProbe, PipStatusProbe

from carolyne.uarch.mem.common.mem_port import MemPortReadValid
from carolyne.uarch.o3.bp.bp_base       import BpBase, BpPrediction
from carolyne.uarch.o3.bp.bp_helper     import bp_field_names
from carolyne.uarch.o3.common_field     import INSTR, NPC, PC, VALID
from carolyne.uarch.o3.config           import CPUO3_Config
from carolyne.uarch.o3.fetch_helper     import build_fetch_table
from carolyne.uarch.o3.priority         import PRI_MIS_PRED


class Fetch(Module):

    def __init__(self,
                 config    : CPUO3_Config,
                 read_ports: Sequence[MemPortReadValid]):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config     = config
        self.read_ports = tuple(read_ports)
        self._reject_bad_ports()
        super().__init__()

    def _reject_bad_ports(self) -> None:
        """One port per LANE, each able to report whether it was answered."""
        lanes = self.config.fe_lanes
        if len(self.read_ports) != lanes:
            raise ValueError(
                f"Fetch: needs one instruction read port per lane, got "
                f"{len(self.read_ports)} for {lanes} lanes")
        for lane, port in enumerate(self.read_ports):
            if not isinstance(port, MemPortReadValid):
                raise TypeError(
                    f"Fetch: read_ports[{lane}] must be a MemPortReadValid — "
                    f"a lane drops its word when the memory does not answer — "
                    f"got {type(port).__name__}")

    @init
    def com_declare(self):
        # constant
        pc_width = self.config.isa.pc_width

        # hardware component
        self.pc          = reg(pc_width, "pc")
        self.pc.reset(self.config.reset_pc)         # the ISA's reset vector
        self.fetch       = build_fetch_table(self.config, "fetch")
        self.fetch_meta  = PipCon()

    # retrieve data you want
    def connect(self, decoder, bp: BpBase):
        self.decode_meta = decoder.decode_meta
        self.bp          = bp       # asked for every lane's next pc

    def on_mis_pred(self, new_pc):
        """A squash empties the stage AND sends it to the corrected pc.

        - the pc write is at PRI_MIS_PRED, above the transfer's own advance,
          so the redirect wins in the cycle both fire
        """
        self.fetch_meta.flush()
        self.override_pc(new_pc, PRI_MIS_PRED)

    def override_pc(self, new_pc, override_priority: int):
        # `|=`, not `=`: a bare assignment rebinds the Python attribute and
        # throws the reg away.
        with priority(override_priority):
            self.pc |= new_pc

    @flow
    def transfer(self):
        # constant
        align = self.config.isa.pc_align

        # step 1: address every port off the pc, no grant, so the word is ready when granted
        lane_pcs = [self.pc + (lane * align)
                    for lane in range(len(self.read_ports))]
        for lane, port in enumerate(self.read_ports):
            port.bind_byte_addr(lane_pcs[lane])
        lane_predictions = self.predict_lanes(lane_pcs)

        # step 2: keep the leading run of answered lanes, cut after a lane predicted taken
        lane_read_valid = [port.read_valid() for port in self.read_ports]
        if self.bp.may_predict_taken:
            kepts = self.keep_until_taken(lane_read_valid, lane_predictions)
        else:
            kepts = self.keep_leading_run(lane_read_valid)

        # step 3: next pc = past the kept lanes, or the taken lane's predicted npc
        step    = sum_cnt(kepts, width=self.config.isa.pc_width)
        next_pc = self.pc + (step << self.config.instr_byte_bits)
        if self.bp.may_predict_taken:
            # at most one lane is kept AND taken (the lane after it is cut),
            # so the order of the muxes does not matter
            for lane, prediction in enumerate(lane_predictions):
                next_pc = mux(kepts[lane] & prediction.taken, prediction.npc, next_pc)

        # step 4: capture the group on EVERY grant (mode="any" would overwrite an unread group)
        pip_metas = [self.decode_meta,
                     *[port.pip_meta for port in self.read_ports]]
        with pip(self.fetch_meta, auto_req = True, auto_restart = True):
            with zync(pip_metas, mode = "all"):
                for lane, port in enumerate(self.read_ports):
                    self.fetch[lane] |= {PC   : lane_pcs[lane],
                                         NPC  : lane_predictions[lane].npc,
                                         INSTR: port.read(),
                                         VALID: kepts[lane],
                                         **lane_predictions[lane].meta}
                self.pc |= next_pc

    def predict_lanes(self, lane_pcs: Sequence) -> tuple:
        """The predictor's answer, one per lane, held to the record it declared."""
        lane_predictions = tuple(self.bp.predict(lane_pcs))
        names = set(bp_field_names(self.config))
        if len(lane_predictions) != len(lane_pcs):
            raise ValueError(
                f"Fetch: {type(self.bp).__name__}.predict returned {len(lane_predictions)} "
                f"predictions for {len(lane_pcs)} lanes")
        for lane, prediction in enumerate(lane_predictions):
            if not isinstance(prediction, BpPrediction):
                raise TypeError(
                    f"Fetch: {type(self.bp).__name__}.predict lane {lane} gave "
                    f"{type(prediction).__name__}, not a BpPrediction")
            if set(prediction.meta) != names:
                raise ValueError(
                    f"Fetch: {type(self.bp).__name__}.predict lane {lane} gave meta "
                    f"{sorted(prediction.meta)}, the spec declares {sorted(names)}")
        return lane_predictions

    @staticmethod
    def keep_until_taken(lane_read_valid: Sequence, lane_predictions: Sequence):
        """keep_leading_run, also cut after the first lane predicted taken.

        - the lanes after a taken branch are on the wrong path; the pc goes
          to the branch's predicted npc instead
        """
        run, so_far = [], None
        for read_valid, prediction in zip(lane_read_valid, lane_predictions):
            so_far = read_valid if so_far is None else so_far & read_valid
            run.append(so_far)
            so_far = so_far & ~prediction.taken
        return run

    @staticmethod
    def keep_leading_run(lane_read_valid: Sequence):
        """Keep a lane only if it and every lower lane answered.

        The pc advances by what is kept, so a gap costs bandwidth rather than
        skipping the instructions behind it.
        """
        run, so_far = [], None
        for read_valid in lane_read_valid:
            so_far = read_valid if so_far is None else so_far & read_valid
            run.append(so_far)
        return run

    @dbg
    def dbg_probes(self):
        self.dbg_fetch_meta = PipStatusProbe(self.fetch_meta)
        self.dbg_fetch      = KarrayProbe   (self.fetch)          # rows in use: the `valid` field
