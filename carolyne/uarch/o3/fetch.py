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

from typing import Sequence

from kathryn import *

from carolyne.uarch.mem.common.mem_port import MemPortReadValid
from carolyne.uarch.o3.common_field import INSTR, PC, VALID
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.fetch_helper import build_fetch_table


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
    def connect(self, decoder):
        self.decode_meta = decoder.decode_meta

    def on_mis_pred(self):
        # a squash empties the stage: clear the grant, the pip auto-restarts
        self.fetch_meta.flush()

    def override_pc(self, new_pc, override_priority: int):
        # `|=`, not `=`: a bare assignment rebinds the Python attribute and
        # throws the reg away.
        with priority(override_priority):
            self.pc |= new_pc

    @flow
    def transfer(self):
        # constant
        align = self.config.isa.pc_align

        # The address takes NO grant: it follows the pc, so the word is already
        # at the port when the transfer is granted instead of one gate behind
        # it. Only the capture is an event.
        for lane, port in enumerate(self.read_ports):
            port.bind_byte_addr(self.pc + (lane * align))

        taken = self.keep_leading_run(
            [port.read_valid() for port in self.read_ports])
        step  = sum_cnt(taken, width=self.config.isa.pc_width)

        # transfer data
        pip_metas = [self.decode_meta,
                     *[port.pip_meta for port in self.read_ports]]
        with pip(self.fetch_meta, auto_req = True, auto_restart = True):
            with zync(pip_metas):
                for lane, port in enumerate(self.read_ports):
                    self.fetch[lane] |= {PC   : self.pc + (lane * align),
                                         INSTR: port.read(),
                                         VALID: taken[lane]}
                self.pc |= self.pc + (step << self.config.instr_byte_bits)

    @staticmethod
    def keep_leading_run(answered: Sequence):
        """Keep a lane only if it and every lower lane answered.

        The pc advances by what is kept, so a gap costs bandwidth rather than
        skipping the instructions behind it.
        """
        run, so_far = [], None
        for ok in answered:
            so_far = ok if so_far is None else so_far & ok
            run.append(so_far)
        return run
