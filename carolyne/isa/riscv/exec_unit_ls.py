# LSExecUnit — loads and stores, TWO stages over the engine's LSQ api.
#
# Stage 0 resolves the WORD once for both directions: effective address,
# store-to-load forwarding search, memory read, and — for a store — the
# byte-merged word, pushed into the store buffer (sub-word stores are a
# read-modify-write through the same forwarding path a load uses). A store
# STALLS here while the buffer is full (the handshake's condition).
#
# Stage 1 extracts the load's bytes from the captured word, sign- or
# zero-extends, and writes rd back; every µop reports fin.
#
# Correctness leans on the LS station issuing IN ORDER: the word captured at
# stage 0 stays the newest older value, because no older store can execute
# after this µop's stage 0.

from __future__ import annotations

from kathryn import HwComponentType, Karray, kaf, mux, val, wire, zif
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from . import uop as U
from .exec_unit_util import drive_by_uop, uop_hit
from .operand import AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3, AOPR_DEST_1
from .reg import X_LEN


class LdStResult(Karray):
    """Stage 0 -> stage 1: this unit's OWN data only.

    The machine's fields (speculation pair, ROB entry, µop kind, rd's
    promised register) arrive from `api.next_stage_fields` at instantiation
    — an ISA package neither spells a uarch field name nor sizes one.
    """
    loaded_word  = kaf(X_LEN)   # the word at the effective address, buffer or memory
    byte_bit_off = kaf(5)       # where the addressed byte starts in it: 0/8/16/24
    half_bit_off = kaf(5)       # where the addressed halfword starts: 0 or 16


class LSExecUnit(ExecUnitBase):
    """Loads and stores over the store buffer and the data memory."""

    def exec_stage(self, stage_idx, src, api):
        if stage_idx == 0:
            return self._address_stage(src, api)
        return self._writeback_stage(src, api)

    # --- stage 0: address, forward, merge, push -------------------------------
    def _address_stage(self, src, api):
        base    = api.get_src(src, AOPR_SRC_1)
        is_st   = uop_hit(src, U.STORES)
        is_ld   = uop_hit(src, U.LOADS)
        # a load's immediate rides src_2 (I-type); a store's data rides
        # src_2 and its immediate src_3 (S-type)
        imm     = mux(is_st, api.get_src(src, AOPR_SRC_3),
                             api.get_src(src, AOPR_SRC_2))
        st_data = api.get_src(src, AOPR_SRC_2)

        # `eff_addr` counts BYTES; memory is addressed by WORDS, so the low
        # two bits pick the byte inside the word rather than the word. Binary
        # masks, because these name address BITS: 0b11 is both, 0b10 the one
        # that picks the halfword. `<< 3` turns a byte offset into a bit one.
        eff_addr      = wire(X_LEN, "ls_eff_addr")
        eff_addr     *= base + imm
        word_addr     = eff_addr >> 2
        byte_bit_off  = (eff_addr & 0b11) << 3             # 0, 8, 16, 24
        half_bit_off  = (eff_addr & 0b10) << 3             # 0 or 16

        # the newest value of the word: a buffered store beats memory
        fwd_hit, fwd_data = api.lsq_search(word_addr)
        loaded_word  = wire(X_LEN, "ls_loaded_word")
        loaded_word *= mux(fwd_hit, fwd_data, api.mem_read(word_addr))

        # a sub-word store merges its bytes into the current word, so the
        # buffer holds full words and forwarding never needs a byte mask
        b_mask = val(X_LEN, 0xff)   << byte_bit_off
        h_mask = val(X_LEN, 0xffff) << half_bit_off
        merged = wire(X_LEN, "st_merged")
        drive_by_uop(merged, src, (
            (U.UOP_SW, st_data),
            (U.UOP_SH, (loaded_word & ~h_mask)
                       | ((st_data & 0xffff) << half_bit_off)),
            (U.UOP_SB, (loaded_word & ~b_mask)
                       | ((st_data & 0xff) << byte_bit_off)),
        ))

        # rd's promised register is named because stage 1 writes it back
        res = LdStResult(HwComponentType.REG, (1,), "ls_res",
                         **api.next_stage_fields(src, AOPR_DEST_1))

        # a store may not move on while the buffer is full; a load always may
        with api.zync_with_next_stage(src, res,
                                      is_ld | ~api.lsq_is_full()): ### it means if it is store it has to have the free entry
            res[0] |= {"loaded_word" : loaded_word,
                       "byte_bit_off": byte_bit_off,
                       "half_bit_off": half_bit_off}
            with zif(is_st):
                api.lsq_push_store(word_addr, merged)
        return res

    # --- stage 1: extract, extend, write back ---------------------------------
    def _writeback_stage(self, src, api):
        # the byte and the halfword the address points at, shifted down to
        # bit 0 and zero-extended — LBU/LHU want them as they stand, LB/LH
        # sign-extend them below
        loaded_word    = to_ref(src[0].loaded_word)
        addressed_byte = (loaded_word >> to_ref(src[0].byte_bit_off)) & 0xff
        addressed_half = (loaded_word >> to_ref(src[0].half_bit_off)) & 0xffff

        load_result = wire(X_LEN, "load_result")
        drive_by_uop(load_result, src, (
            (U.UOP_LW,  loaded_word),
            (U.UOP_LBU, addressed_byte),
            (U.UOP_LHU, addressed_half),
            # sign extension by wraparound: (v ^ sign) - sign
            (U.UOP_LB,  (addressed_byte ^ 0x80)   - 0x80),
            (U.UOP_LH,  (addressed_half ^ 0x8000) - 0x8000),
        ))

        with zif(uop_hit(src, U.LOADS)):
            api.wb_reg(AOPR_DEST_1, load_result)
        api.declare_fin(src)
        return None
