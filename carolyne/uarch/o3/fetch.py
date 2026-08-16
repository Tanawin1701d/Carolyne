from typing import Optional

from kathryn import *

from carolyne.uarch.common import BlockManager


##################################################################
#
# DATA STRUCTURE
#
##################################################################


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

    def __init__(self, lane):




