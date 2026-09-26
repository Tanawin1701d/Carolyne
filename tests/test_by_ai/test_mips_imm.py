# MIPS32's immediate rules held against the manual's own encoders, on plain
# INTS — no Kathryn, no engine.

import random

from carolyne.isa import ImmApi
from carolyne.isa.mips import imm as M
from carolyne.isa.mips.operand import (OPR_BITFIELD_EXT, OPR_BITFIELD_INS, OPR_IMM_BR,
                                       OPR_IMM_J, OPR_IMM_LUI, OPR_IMM_S16, OPR_IMM_S16_ST,
                                       OPR_IMM_Z16, OPR_SA)
from carolyne.uarch.common import extract_imm_value

M32 = (1 << 32) - 1


def run(rule, word, width=32):
    api = ImmApi(width)
    rule(word, api)
    return api.value & M32


# --- the manual's encoders ------------------------------------------------------
def _enc_i16(v):            return v & 0xFFFF
def _enc_br(off_bytes):     return (off_bytes >> 2) & 0xFFFF
def _enc_j(target_bytes):   return (target_bytes >> 2) & 0x3FFFFFF
def _enc_bitfield(pos, msb): return (pos << 6) | (msb << 11)


def test_the_signed_sixteen_bit_form_round_trips_over_its_whole_range():
    for v in range(-32768, 32768):
        assert run(M.imm_s16, _enc_i16(v)) == v & M32


def test_the_zero_extended_form_is_the_default_and_reads_the_field_as_is():
    assert OPR_IMM_Z16.imm_extract is None and OPR_SA.imm_extract is None
    for v in (0, 1, 0x7FFF, 0x8000, 0xFFFF):
        assert extract_imm_value(_enc_i16(v), OPR_IMM_Z16) == v
    assert extract_imm_value(0b11111 << 6, OPR_SA) == 31


def test_lui_lands_in_the_top_half():
    for v in (0, 1, 0x8000, 0xFFFF, 0x1234):
        assert run(M.imm_lui, _enc_i16(v)) == (v << 16) & M32


def test_a_branch_offset_round_trips_over_its_whole_range_in_word_steps():
    # imm16 << 2, sign-extended from bit 17: the offset is relative to the
    # delay slot's pc, which the body adds (exec_unit_br.py)
    for off in range(-(1 << 17), 1 << 17, 4):
        assert run(M.imm_br, _enc_br(off)) == off & M32


def test_a_jump_index_becomes_the_low_28_bits_of_the_target():
    # the top four bits come from the pc, so the rule zero-extends
    samples = [0, 4, 0x0FFFFFFC, 0x08000000, 0xBFC00040, 0xFFFFFFFC]
    samples += [random.Random(7).randrange(0, 1 << 32) & ~3 for _ in range(500)]
    for target in samples:
        assert run(M.imm_j, _enc_j(target)) == target & 0x0FFFFFFC


def test_the_bitfield_immediate_packs_both_positions():
    # ext: pos at bits 4..0, size-1 at bits 12..8; ins: lsb and msb likewise
    for pos in range(32):
        for msb in range(32):
            value = run(M.imm_bitfield, _enc_bitfield(pos, msb))
            assert value & 0x1F == pos and (value >> 8) & 0x1F == msb
            assert value >> 13 == 0 and (value >> 5) & 0b111 == 0


def test_every_placed_immediate_states_its_rule_and_the_engine_runs_it():
    for operand in (OPR_IMM_S16, OPR_IMM_S16_ST, OPR_IMM_LUI, OPR_IMM_BR, OPR_IMM_J,
                    OPR_BITFIELD_EXT, OPR_BITFIELD_INS):
        assert operand.imm_extract is not None
    assert extract_imm_value(_enc_i16(-5), OPR_IMM_S16) & M32 == -5 & M32
    assert extract_imm_value(_enc_br(-8), OPR_IMM_BR) & M32 == -8 & M32
    assert extract_imm_value(_enc_i16(0xBFC0), OPR_IMM_LUI) == 0xBFC00000
