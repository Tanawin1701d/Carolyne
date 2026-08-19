from typing import Optional

from kathryn import *

from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.easy_mem import EasyMem


class FetchDT(Karray):
    # it is per lane Karray
    #
    # The widths are DEFAULTS. Both are settable at instantiation, so one
    # record class serves any ISA:
    #
    #   self.fetch = FetchDT(HwComponentType.REG, (lanes,), "fetch",
    #                        pc=isa.pc_width, instr=isa.ilen_bytes * 8)
    pc    = kaf(32)
    instr = kaf(32)

class Fetch(Module):

    def __init__(self,
                 config: CPUO3_Config,
                 simple_mem: EasyMem):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config     = config
        self.simple_mem = simple_mem
        super().__init__()

    @init
    def com_declare(self):
        # constant
        pc_width = self.config.isa.pc_width
        pc_align = self.config.isa.pc_align
        lanes    = self.config.fe_lanes

        # hardware component
        self.pc          = reg(pc_width, "pc")
        self.mem_req     = [ self.simple_mem.read_sync(i, self.pc + (i * pc_align))
                             for i in range(lanes)]
        self.fetch_stages = [ FetchDT(HwComponentType.REG, (1,),
                                     "fetchDT{}".format(i),
                                     pc=pc_width,
                                     instr=self.config.instr_width)
                             for i in range(lanes)]
        self.fetch_meta  = PipCon()

    # retrieve data you want
    def connect(self, decoder):
        self.decode_meta = decoder.decode_meta

    def override_pc(self, new_pc, override_priority: int):
        # `|=`, not `=`: a bare assignment rebinds the Python attribute and
        # throws the reg away.
        with priority(override_priority):
            self.pc |= new_pc



    @flow
    def transfer(self):
        # transfer data
        pip_meta = [ self.decode_meta, *[req[0] for req in  self.mem_req]]
        with pip(self.fetch_meta, auto_req = True):
            with zync(pip_meta):
                # constant
                lanes = self.config.fe_lanes
                pc_align = self.config.isa.pc_align
                # actual hardware transfer
                for i in range(lanes):
                    self.fetch_stages[i][0].pc    |= self.pc + (i * pc_align)
                    self.fetch_stages[i][0].instr |= self.mem_req[i][1]
                self.pc |= self.pc + lanes * pc_align