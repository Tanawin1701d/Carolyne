# Decode: the stage between fetch and rename. It reads the fetched
# instruction WORD and writes the µop record the rest of the core reads.
#
# This is the ONE place raw ISA bits are turned into the engine's vocabulary.
# After it nothing carries an encoding (uop_contract.md §2): a decoded lane
# says WHICH µop of the ISA it is (`uop_idx`), which slots that µop fills, and
# the architectural register or immediate each slot names.
#
# The tree each mop is decoded by comes from decode_tree.py (no hardware
# there). This file walks it into hardware, per lane:
#
#   pip(decode_meta)
#   └─ zync(next_meta)                       one grant moves every lane
#      └─ for each lane
#         ├─ valid = 0                       PRI_DECODE_DEFAULT: stands when nothing matches
#         └─ zif(fetch[lane].valid)          a lane with no word decodes nothing
#            ├─ zif(opcode == OP)            mop_shared_fields: pc, npc, bp record,
#            │  │                            operand groups every µop of the mop fills alike
#            │  └─ case (dec_field funct3)   node_decode: the field on its own wire
#            │     ├─ 3'b000: case (dec_field funct7)
#            │     │  ├─ 7'b0000000: ADD     uop_fields: valid=1, uop_idx, is_branch,
#            │     │  ├─ 7'b0100000: SUB     is_store, rsv_id, the groups not shared
#            │     │  └─ 7'b0000001: MUL
#            │     └─ ...
#            ├─ zif(opcode == OP-IMM)        mops exclude each other by the encoding
#            │  └─ ...                       table, so their zifs need no priority
#            └─ ...
#
# What one decoded lane holds for `addi x5, x6, -4`:
#
#   valid  uop_idx  rsv_id        src_1 active/ar_idx  src_2 active/valid/data  dest_1 active/ar_idx
#   1      ADDI     ALU station   1 / x6               1 / 1 / 0xFFFFFFFC      1 / x5
#
# - zstate takes a whole signal: a slice passed to it is dropped, so each
#   switched field is driven onto a wire of its own first (dec_field_*)
# - the tree names are re-exported here: the compile tool imports
#   group_uops_by_level from this module

from typing import Optional

from kathryn        import *
from kathryn.signal import to_ref

from carolyne.debug.sim              import KarrayProbe, PipStatusProbe
from carolyne.isa                    import Operand, Uop
from carolyne.uarch.common           import extract_arch_index, extract_imm_value, match_field_bits
from carolyne.uarch.o3.bp.bp_helper  import bp_field_names
from carolyne.uarch.o3.common_field  import IS_BRANCH, IS_STORE, NPC, PC, RSV_ID, UOP_IDX
from carolyne.uarch.o3.config        import CPUO3_Config
from carolyne.uarch.o3.decode_helper import DecodeEntryBase, build_decode_table, decode_atm_operands
from carolyne.uarch.o3.decode_tree   import (DecodeLeaf, DecodeNode, DecodeSwitch, MopTree,  # noqa: F401  re-exported
                                             build_decode_tree, group_uops_by_level, mop_uops)
from carolyne.uarch.o3.fetch_helper  import FetchEntryBase
from carolyne.uarch.o3.operand_field import ACTIVE, AR_IDX, DATA, VALID, WB_REQUIRED, field_name
from carolyne.uarch.o3.priority      import PRI_DECODE_DEFAULT


class Decode(Module):

    def __init__(self, config: CPUO3_Config):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config = config
        super().__init__()

    @init
    def com_declare(self):
        # Core-wide, srcs then dests: the record has a slot for every operand
        # the ISA declares, and a given µop fills only some — the rest must
        # still be WRITTEN (zeros), because the rows are REGs and silence
        # would keep the previous instruction's claim.
        self.atm_operands = decode_atm_operands(self.config.isa)
        self.mop_trees    = build_decode_tree  (self.config.isa)
        self.bp_fields    = bp_field_names     (self.config)   # copied as fetch wrote them

        self.decode      = build_decode_table(self.config, "decode")
        self.decode_meta = PipCon()

        self.fetch     = None       # the fetch stage's rows, from connect()
        self.next_meta = None       # the consumer's arb, from connect()

        self._imm_wire_cnt   = 0    # names the per-extraction immediate wires
        self._field_wire_cnt = 0    # names the per-switch field wires

    # retrieve data you want
    def connect(self, fetcher, dispatcher):
        """Fill the stage's slots from its neighbours: the fetched rows this
        stage decodes, and the consumer arb its transfer zyncs against."""
        self.fetch     = fetcher.fetch
        self.next_meta = dispatcher.dispatch_meta

    def on_mis_pred(self):
        # a squash empties the stage: clear the grant, the pip auto-restarts
        self.decode_meta.flush()

    @flow
    def transfer(self):
        """The stage body: one decoded record per lane, on the consumer's grant.

        - named `transfer`, not `decode`: `self.decode` is the TABLE
        """
        with pip(self.decode_meta, auto_restart=True):
            with zync(self.next_meta):
                for lane in range(self.config.fe_lanes):
                    self.write_lane_default(self.decode[lane])
                    self.lane_decode(lane, self.fetch[lane])

    def lane_decode(self, lane: int, fetch_entry: FetchEntryBase):
        """One lane: one independent zif per mop, its tree inside.

        - all of it is under the lane's `valid`: a lane whose bank did not
          answer has no word, so write_lane_default's valid=0 stands
        """
        word = to_ref(fetch_entry.instr)
        with zif(to_ref(fetch_entry.valid)):
            for mop_tree in self.mop_trees:
                mop = mop_tree.mop
                with zif(match_field_bits(word, mop.matcher_field, mop.matcher_value)):
                    shared = self.mop_shared_fields(mop_tree, lane, fetch_entry)
                    self.decode[lane] |= shared
                    self.node_decode(mop_tree.root, lane, word, set(shared))

    def mop_shared_fields(self, mop_tree: MopTree, lane: int, fetch_entry: FetchEntryBase) -> dict:
        """The fields every µop of the mop writes alike: pc, npc, the bp
        record, and each operand group whose rule is the same for all."""
        word  = to_ref(fetch_entry.instr)
        uops  = mop_uops(mop_tree.root)
        row   = {PC : to_ref(fetch_entry.pc),
                 NPC: to_ref(fetch_entry.npc)}           # the predictor's, from fetch
        row.update({name: to_ref(getattr(fetch_entry, name)) for name in self.bp_fields})
        for atm_opr in self.atm_operands:
            keys = {self.operand_key(uop, atm_opr) for uop in uops}
            if len(keys) == 1:
                row.update(self.build_atm_operand_value(word, atm_opr,
                                                        self.operand_of(uops[0], atm_opr),
                                                        uops[0].has_feature(IS_BRANCH)))
        return row

    def node_decode(self, node: DecodeNode, lane: int, word, shared: set):
        """A tree node: a zstate over its field, or the µop's own fields."""
        if isinstance(node, DecodeSwitch):
            # zstate takes a whole signal: a slice passed to it is dropped, so
            # the field is driven onto a wire of its own first
            field  = wire(node.end - node.start, f"dec_field_{lane}_{node.start}_{self._field_wire_cnt}")
            self._field_wire_cnt += 1
            field *= word[node.end - 1, node.start]
            with zstate(field):
                for value, child in node.cases:
                    with zcase(value):
                        self.node_decode(child, lane, word, shared)
            return
        # A DecodeLeaf: the path ends in one µop. Write the fields only this
        # µop sets; the mop's zif already wrote the `shared` ones.
        #
        #   zif(opcode == OP)         pc, npc, bp record, shared operand groups
        #   └─ case funct3: 3'b000
        #      └─ case funct7: 7'b0100000
        #         └─ HERE (SUB)       valid=1, uop_idx=SUB, is_branch=0, is_store=0,
        #                             rsv_id, and every operand group not in `shared`
        self.decode[lane] |= self.uop_fields(node.uop, lane, word, shared)

    def uop_fields(self, uop: Uop, lane: int, word, shared: set) -> dict:
        """What only this µop writes: valid, its kind, and the operand groups
        its mop does not share.

        - is_branch / is_store come from the TEMPLATE (Uop.specified_feature),
          rsv_id from the MACHINE (rsv_id_for); all three are constants
        - unfilled operand slots are written ZERO: the rows are REGs, and
          silence would keep the previous instruction's claim
        """
        row = {VALID    : 1,
               UOP_IDX  : uop.uop_idx,
               IS_BRANCH: int(uop.has_feature(IS_BRANCH)),
               IS_STORE : int(uop.has_feature(IS_STORE)),
               RSV_ID   : self.rsv_id_for(uop, lane)}
        for atm_opr in self.atm_operands:
            group = self.build_atm_operand_value(word, atm_opr, self.operand_of(uop, atm_opr),
                                                 uop.has_feature(IS_BRANCH))
            row.update({name: value for name, value in group.items() if name not in shared})
        return row

    @staticmethod
    def operand_of(uop: Uop, atm_opr) -> Optional[Operand]:
        """The slot rule `uop` fills `atm_opr` with, or None for an empty slot.

        - at most one: Uop refuses an atomic operand filled twice
        """
        return next((operand for operand in (*uop.srcs, *uop.dests)
                     if operand.atomic is atm_opr), None)

    def operand_key(self, uop: Uop, atm_opr) -> tuple:
        """Two µops write `atm_opr`'s group alike when this key is equal."""
        operand = self.operand_of(uop, atm_opr)
        return (None if operand is None else id(operand),
                atm_opr.is_dest and uop.has_feature(IS_BRANCH))

    def write_lane_default(self, decode_entry: DecodeEntryBase):
        """The empty-lane default: valid=0, once per lane. Call it in the SAME
        granted scope as the match guards, OUTSIDE them.
        """
        with priority(PRI_DECODE_DEFAULT):
            decode_entry |= {VALID: 0}

    def build_imm(self, word, operand):
        """The operand's immediate, driven onto a wire of its own width.

        - the rule is the ISA's (`Operand.imm_extract`); it drives the wire
          slice by slice, so bits nothing places read zero
        """
        out = wire(operand.width,
                   f"imm_{operand.atomic.name}_{self._imm_wire_cnt}")
        self._imm_wire_cnt += 1
        return extract_imm_value(word, operand, out)

    def build_atm_operand_value(self, word, atm_opr, operand, is_branch) -> dict:
        """What one atomic operand's fields HOLD for this µop, keyed by name.

        decode_helper.decode_operand_fields builds the same group's SHAPE; this
        fills it. A slot the µop leaves empty reads zero.

        - only kinds the record actually has are written
        - `data` needs a has_imm source; `ar_idx` only where the class
          has an index to choose (has_arch, index_width > 0)
        - a BRANCH forces every dest slot ACTIVE even when the µop leaves it
          empty, so rename allocates a physical register the squash can roll
          the pointer back to; `wb_required` stays off there, so commit frees
          that register without making anything architectural
        """
        filled = operand is not None
        active = filled or (is_branch and atm_opr.is_dest)
        group  = {field_name(ACTIVE, atm_opr): int(active)}

        if atm_opr.is_src:
            # valid = the value is already known: an IMMEDIATE, whose
            # matcher says which bits. A matcher-less µtemp target is a
            # LINKING µtemp: an earlier µop of this crack produces it, so
            # nothing is known at decode.
            # LIMIT: nothing wakes a linking µtemp downstream yet — that is
            # the cracker/rename story, not decode's.
            is_imm = (filled and operand.is_intermediate
                      and operand.matcher is not None)
            group[field_name(VALID, atm_opr)] = int(is_imm)
            if atm_opr.has_imm:
                group[field_name(DATA, atm_opr)] = (self.build_imm(word, operand)
                                                    if is_imm else 0)
        else:
            # FILLED, not active: a forced-active branch slot has no writeback
            # coming, and commit must not wait for one
            group[field_name(WB_REQUIRED, atm_opr)] = int(filled)

        if atm_opr.has_arch and atm_opr.reg_file.index_width:
            group[field_name(AR_IDX, atm_opr)] = (extract_arch_index(word, operand)
                                                  if filled and operand.is_arch
                                                  else 0)
        return group

    def rsv_id_for(self, uop: Uop, lane: int) -> int:
        """Which station this lane sends that µop to. STATIC: a constant per
        (µop, lane), so the decoder wires it and builds no comparison.
        """
        ids = self.config.rsv_ids_for(uop)
        return ids[lane % len(ids)]

    @dbg
    def dbg_probes(self):
        self.dbg_decode_meta = PipStatusProbe(self.decode_meta)
        self.dbg_decode      = KarrayProbe   (self.decode)        # rows in use: the `valid` field
