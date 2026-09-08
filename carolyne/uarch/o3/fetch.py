# Fetch — one instruction word per front-end lane, per cycle.
#
# The stage holds READ PORTS, not a memory: the machine builds the instruction
# memory outside the core and hands one port per lane in (mem/mem_port.py).
# Lane i drives its port's index and reads its word back in the same cycle.
#
# THE BANKS ARE INTERLEAVED, and a lane IS a bank. A word address splits
# | index | bank |, the low log2(fe_lanes) bits picking the bank, and lane k's
# port is bound to bank k at elaboration — so every lane drives the SAME index
# and its own bank supplies its word. The program is stored once, spread across
# the banks: word w sits in bank w % fe_lanes at index w / fe_lanes.
#
# LIMIT: the pc must be aligned to a whole fetch group (fe_lanes * ilen_bytes).
# One index reaches the group's base, so a pc part-way into a group makes every
# lane read that group from the start while the recorded pcs count on from the
# pc itself. Sequential fetch keeps the alignment (the pc steps by a whole
# group); a redirect to an arbitrary target does not, and nothing realigns it
# yet.

from typing import Optional, Sequence

from kathryn import *

from carolyne.uarch.common import ceil_log2
from carolyne.uarch.mem.common.mem_port import MemPortRead
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.fetch_helper import build_fetch_table


class Fetch(Module):

    def __init__(self,
                 config    : CPUO3_Config,
                 read_ports: Sequence[MemPortRead]):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config     = config
        self.read_ports = tuple(read_ports)
        if len(self.read_ports) != config.fe_lanes:
            raise ValueError(
                f"Fetch: needs one instruction read port per front-end lane, "
                f"got {len(self.read_ports)} for {config.fe_lanes} lanes")
        for lane, port in enumerate(self.read_ports):
            if not isinstance(port, MemPortRead):
                raise TypeError(
                    f"Fetch: read_ports[{lane}] must be a MemPortRead, "
                    f"got {type(port).__name__}")
        super().__init__()

    @init
    def com_declare(self):
        # constant
        pc_width = self.config.isa.pc_width

        # hardware component
        self.pc          = reg(pc_width, "pc")
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

    def mem_index(self):
        """The instruction memory index EVERY lane reads this cycle.

        One index, not one per lane: the low address bits pick the bank and a
        lane's port is already bound to its own, so the index names the fetch
        GROUP. A part-select, not a shift — the bits below are the byte offset
        and the bank, and the bits above are past the memory.
        """
        shift = (  ceil_log2(self.config.isa.ilen_bytes)   # byte offset -> word
                 + ceil_log2(self.config.fe_lanes))        # word -> bank
        width = self.config.instr_mem_idx_width
        return self.pc[width + shift - 1, shift]

    @flow
    def transfer(self):
        # The address takes NO grant: it follows the pc, so the word is already
        # at the port when the transfer is granted instead of one gate behind
        # it. Only the capture is an event.
        group_index = self.mem_index()          # one index, every lane
        for port in self.read_ports:
            port.bind_addr(group_index)

        # transfer data
        pip_metas = [self.decode_meta, *[port.pip_meta for port in self.read_ports]]
        with pip(self.fetch_meta, auto_req = True, auto_restart = True):
            with zync(pip_metas):
                # constant
                lanes    = self.config.fe_lanes
                pc_align = self.config.isa.pc_align
                # actual hardware transfer
                for i in range(lanes):
                    self.fetch[i].pc    |= self.pc + (i * pc_align)
                    self.fetch[i].instr |= self.read_ports[i].read()
                self.pc |= self.pc + lanes * pc_align
