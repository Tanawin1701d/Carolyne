# Decode — the stage between fetch and rename: it reads the fetched
# instruction WORD and writes the µop record the rest of the core speaks.
#
# This is the ONE place raw ISA bits are turned into the engine's vocabulary.
# After it nothing carries an encoding (uop_contract.md §2): a decoded lane
# says WHICH µop of the ISA it is (`uop_idx`), which slots that µop fills, and
# the architectural register or immediate each slot names.
#
# A UopSeq may crack an instruction into SEVERAL µops. Decode walks them
# breadth-first, one LEVEL per cycle:
#
#   pip:  seq:  zync(level 1): zif(hit): first µop of each crack
#               zync(level 2): zif(hit): second µop, ...
#
# - each seq child is one cycle; each level hands over on the consumer's
#   grant (zync), so the walk paces itself on the handshake
# - the pip holds fetch for the whole walk: the instr word is stable
# - a level nothing matches hands a bubble (valid=0, the lane default)
# - `group_uops_by_level` is the mop table flattened for that walk

from kathryn import *
from kathryn.signal import to_ref

from carolyne.isa import IsaBase, Mop, Uop, UopSeq
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.common import (extract_arch_index, extract_imm_value,
                                   match_field_bits)
from carolyne.uarch.o3.decode_helper import (build_decode_table,
                                             decode_atm_operands,
                                             DecodeEntryBase)
from carolyne.uarch.o3.priority import PRI_DECODE_DEFAULT
from carolyne.uarch.o3.fetch_helper import FetchEntryBase
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, DATA, VALID,
                                             WB_REQUIRED, field_name)


def _collect_matchers(mop: Mop, uop_seq: UopSeq) -> tuple:
    """Every stated (field, value) rule of one (mop, uop_seq) — its guard.

    - the mop's rule, then the uop_seq's — the whole encoding side; a µop
      template carries no matcher
    - a half-stated matcher (field, no value) tests nothing and is dropped
    """
    pairs = [(mop.matcher_field,     mop.matcher_value),
             (uop_seq.matcher_field, uop_seq.matcher_value)]

    # a stated value always has its field (check_matcher_pair, at
    # construction), so value alone decides
    return tuple((field, value) for field, value in pairs if value is not None)


def group_uops_by_level(isa: IsaBase) -> tuple:
    """The mop table flattened for the level walk.

    - one guard per (mop, uop_seq): EVERY stated rule on it — the SAME
      conjunction at every level, so identity cannot drift mid-crack
    - a (mop, uop_seq) with no rule at all is refused: nothing tells it apart
    - levels[k] = ((matchers, uop), ...) for every uop_seq longer than k;
      len(levels) = the ISA's longest crack
    """
    # step 1 — per (mop, uop_seq): its guard rules + its µops
    guarded_seqs = []
    for mop in isa.mops:
        for uop_seq in mop.uop_seq:
            matchers = _collect_matchers(mop, uop_seq)
            if not matchers:
                raise ValueError(
                    f"ISA '{isa.name}': the crack starting at µop "
                    f"'{uop_seq.uops[0].name}' has no (field, value) rule "
                    f"at all — nothing tells its encoding from its "
                    f"neighbours'")
            guarded_seqs.append((matchers, uop_seq.uops))

    # step 2 — group by level: levels[k] = the k-th µop of every longer crack
    n_levels = max(len(uops) for _matchers, uops in guarded_seqs)
    levels   = []
    for level in range(n_levels):
        alive = tuple((matchers, uops[level])
                      for matchers, uops in guarded_seqs
                      if len(uops) > level)
        levels.append(alive)
    return tuple(levels)


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
        self.levels       = group_uops_by_level(self.config.isa)

        self.decode      = build_decode_table(self.config, "decode")
        self.decode_meta = PipCon()

        self.fetch     = None       # the fetch stage's rows, from connect()
        self.next_meta = None       # the consumer's arb, from connect()

    # retrieve data you want
    def connect(self, fetcher, dispatcher):
        """Fill the stage's slots from its neighbours: the fetched rows this
        stage decodes, and the consumer arb its transfer zyncs against."""
        self.fetch     = fetcher.fetch
        self.next_meta = dispatcher.dispatch_meta

    @flow
    def transfer(self):
        """The stage body: the breadth-first walk over crack levels.

        - one seq child per level = one CYCLE per level (longest crack = N)
        - every level zyncs on the consumer's arb: its writes fire on the
          grant, so the walk paces itself on the handshake
        - the pip holds fetch for the whole walk (instr stays stable), and
          a level nothing matches hands a bubble (the lane default)
        - named `transfer`, not `decode`: `self.decode` is the TABLE
        """
        with pip(self.decode_meta):
            with seq():
                for level in range(len(self.levels)):
                    with zync(self.next_meta):
                        for lane in range(self.config.fe_lanes):
                            self.write_lane_default(self.decode[lane])
                            self.mop_decode(level,
                                            self.fetch[lane],
                                            self.decode[lane])

    def mop_decode(self,
                   level       : int,
                   fetch_entry : FetchEntryBase,
                   decode_entry: DecodeEntryBase):
        """One level of the walk for this lane: the match guards.

        - one INDEPENDENT zif per (mop, uop_seq) alive at this level — the
          encodings are mutually exclusive, so no chain and no priority
        - call it inside the level's zync, beside write_lane_default
        """
        word = to_ref(fetch_entry.instr)
        for matchers, uop in self.levels[level]:
            hit = None
            for field, value in matchers:
                compare = match_field_bits(word, field, value)
                hit     = compare if hit is None else hit & compare
            with zif(hit):
                self.uop_decode(uop, fetch_entry, decode_entry)

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

        # TODO: fix the decode later — fill is_branch / is_store / rsv_id
        # from the real rules instead of the constant zeros below.
        # LIMIT: the description cannot yet say which µops are branches or
        # stores, and the µop→station routing rule is not built — so every
        # decode reads non-branch, non-store, station 0. The real rules swap
        # in here; the writes must exist even so, because the rows are REGs
        # and silence would keep the previous instruction's claim.
        row = {"valid"    : 1,
               "pc"       : pc,
               "npc"      : pc + self.config.isa.ilen_bytes,
               "uop_idx"  : uop.uop_idx,
               "is_branch": 0,
               "is_store" : 0,
               "rsv_id"   : 0}
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
            # valid = the value is already in hand — an IMMEDIATE, whose
            # matcher says which bits. A matcher-less µtemp target is a
            # LINKING µtemp: an earlier µop of this crack produces it, so
            # nothing is in hand at decode.
            # LIMIT: nothing wakes a linking µtemp downstream yet — that is
            # the cracker/rename story, not decode's.
            is_imm = (active and operand.is_intermediate
                      and operand.matcher is not None)
            group[field_name(VALID, atm_opr)] = int(is_imm)
            if atm_opr.has_imm:
                group[field_name(DATA, atm_opr)] = (extract_imm_value(word, operand)
                                                    if is_imm else 0)
        else:
            # only a DEST_W_REQ core has the field; there the bit is active
            if atm_opr.is_write_required:
                group[field_name(WB_REQUIRED, atm_opr)] = int(active)

        if atm_opr.has_arch and atm_opr.reg_file.index_width:
            group[field_name(AR_IDX, atm_opr)] = (extract_arch_index(word, operand)
                                                  if active and operand.is_arch
                                                  else 0)
        return group
