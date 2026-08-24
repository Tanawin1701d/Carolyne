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
from kathryn.signal import to_ref

from carolyne.isa import IsaBase, Uop
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.common import extract_arch_index, extract_imm_value
from carolyne.uarch.o3.decode_helper import (build_decode_table,
                                             decode_atm_operands,
                                             DecodeEntryBase)
from carolyne.uarch.o3.priority import PRI_DECODE_DEFAULT
from carolyne.uarch.o3.fetch_helper import FetchEntryBase
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, DATA, VALID,
                                             WB_REQUIRED, field_name)


class laneDecoder:

    def __init__(self, isa: IsaBase):
        self.isa          = isa
        # Core-wide, srcs then dests: the record has a slot for every operand
        # the ISA declares, and a given µop fills only some — the rest must
        # still be WRITTEN (zeros), because the rows are REGs and silence
        # would keep the previous instruction's claim.
        self.atm_operands = decode_atm_operands(isa)

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
        """The WHOLE record for a lane that decoded to this µop, one assign.

        - runs inside the caller's match guard (the zif that picked this µop)
        - one `|=` for the whole row: no two writes at equal priority
        - valid=1, pc, npc ride along; the no-hit half is
          write_lane_default's valid=0, one rung below
        - unfilled operand slots are written ZERO — the rows are REGs, and
          silence would keep the previous instruction's claim
        """
        word = to_ref(fetch_entry.instr)
        pc   = to_ref(fetch_entry.pc)

        # atomic operand -> the slot rule this µop fills it with, by identity.
        filled = {}
        for operand in (*uop.srcs, *uop.dests):
            if id(operand.atomic) in filled:
                raise ValueError(
                    f"µop '{uop.name}' fills atomic operand "
                    f"'{operand.atomic.name}' twice — one record group "
                    f"cannot say both")
            filled[id(operand.atomic)] = operand

        row = {"valid"  : 1,
               "pc"     : pc,
               "npc"    : pc + self.isa.ilen_bytes,
               "uop_idx": uop.uop_idx}
        for atm_opr in self.atm_operands:
            operand = filled.get(id(atm_opr))   # None = this µop leaves it empty
            group   = self._operand_group(word, atm_opr, operand)
            row.update(group)
        decode_entry |= row

    def write_lane_default(self, decode_entry: DecodeEntryBase):
        """The empty-lane default: valid=0, once per lane.

        - call it in the SAME granted scope as the match guards, OUTSIDE them
        - one rung below the row writes (PRI_DECODE_DEFAULT), so any matched
          branch beats it and a no-hit lane decodes to empty
        """
        with priority(PRI_DECODE_DEFAULT):
            decode_entry |= {"valid": 0}

    def _operand_group(self, word, atm_opr, operand) -> dict:
        """One atomic operand's fields for this µop: filled, zeros elsewhere.

        - mirrors decode_helper.decode_operand_fields: only kinds the record
          has are written
        - `data` rides on a has_imm source; `ar_idx` only where the class
          has an index to choose (has_arch, index_width > 0)
        """
        active = operand is not None
        group  = {field_name(ACTIVE, atm_opr): int(active)}

        if atm_opr.is_src:
            # valid = the value is already in hand, which is what an
            # immediate is; a register slot waits for rename in its station.
            is_imm = active and operand.is_intermediate
            group[field_name(VALID, atm_opr)] = int(is_imm)
            if atm_opr.has_imm:
                group[field_name(DATA, atm_opr)] = (extract_imm_value(word, operand)
                                                    if is_imm else 0)
        else:
            group[field_name(WB_REQUIRED, atm_opr)] = int(active
                                                          and atm_opr.is_write_required)

        if atm_opr.has_arch and atm_opr.reg_file.index_width:
            group[field_name(AR_IDX, atm_opr)] = (extract_arch_index(word, operand)
                                                  if active and operand.is_arch
                                                  else 0)
        return group



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
