# Decode — the stage between fetch and rename: it reads the fetched
# instruction WORD and writes the µop record the rest of the core speaks.
#
# This is the ONE place raw ISA bits are turned into the engine's vocabulary.
# After it nothing carries an encoding (uop_contract.md §2): a decoded lane
# says WHICH µop of the ISA it is (`uop_idx`), which slots that µop fills, and
# the architectural register or immediate each slot names.
#
# `decode_templates` is the mop table flattened for that job: mop → variant →
# µop becomes one template per decodable instruction, carrying every (field,
# value) rule on its path and the µop's place in the ISA's vocabulary.

from kathryn import *

from carolyne.isa import IsaBase, Uop
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.decode_helper import (build_decode_table,
                                             decode_atm_operands,
                                             DecodeEntryBase)
from carolyne.uarch.o3.fetch_helper import FetchEntryBase


class laneDecoder:

    def decode(isa: IsaBase,
               fetch_entry: FetchEntryBase,
               decode_entry: DecodeEntryBase):
        pass


    def mop_decode(self):
        pass

    def uop_decode(self,
                   uop         : Uop,
                   fetch_entry : FetchEntryBase,
                   decode_entry: DecodeEntryBase):
        pass



class Decode(Module):

    def __init__(self, config: CPUO3_Config):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config = config
        super().__init__()

    @init
    def com_declare(self):
        self.templates   = decode_templates(self.config.isa)
        self.atm_operands = decode_atm_operands(self.config.isa)

        self.decode      = build_decode_table(self.config, "decode")
        self.decode_meta = PipCon()

        self.fetch     = None       # the fetch stage's rows, from connect()
        self.next_meta = None       # the consumer's arb, from connect()
