# Immediate extraction: the api an ISA states its rule through, RV32I's five
# rules held against the spec's own encoders, and the one default.
#
# These run on plain INTS — place/sign_extend are operator arithmetic, so an
# ISA's extraction rule is testable with no Kathryn and no engine at all.

import pytest

from carolyne.isa import AtomicOperand, ImmApi, InstrFieldMatch, Operand
from carolyne.isa.atomic_operand import OperandRole, TargetKind
from carolyne.isa.reg import Intermediate, RegFile
from carolyne.isa.riscv import imm as R
from carolyne.isa.riscv import field_match as FM
from carolyne.isa.riscv.operand import (OPR_IMM_B, OPR_IMM_I, OPR_IMM_J,
                                        OPR_IMM_S, OPR_IMM_SHAMT, OPR_IMM_U)
from carolyne.uarch.common import extract_imm_value

SRC, DEST  = OperandRole.SRC, OperandRole.DEST
ARCH, IMM  = TargetKind.ARCH, TargetKind.IMM
M32        = (1 << 32) - 1


def run(rule, word, width=32):
    """A rule writes through the api; int mode reads the value back."""
    api = ImmApi(width)
    rule(word, api)
    return api.value & M32


# --- the api ------------------------------------------------------------------
def test_place_drives_the_stated_slice_and_leaves_the_rest_zero():
    api = ImmApi(32)
    api.place(0xAB, 7, 4, at=8)          # bits 7..4 of 0xAB = 0xA, at bit 8
    assert api.value == 0xA00
    # nothing above the segment survives, so placements never contend
    api2 = ImmApi(32)
    api2.place(0xFFFF, 3, 0, at=0)
    assert api2.value == 0xF


def test_placements_accumulate_into_disjoint_slices():
    api = ImmApi(32)
    api.place(0xF0, 7, 4, at=0)          # -> 0xF
    api.place(0x0F, 3, 0, at=8)          # -> 0xF00
    assert api.value == 0xF0F


@pytest.mark.parametrize("placed,expect", [(0xFFF, M32), (0x001, 1),
                                           (0x800, M32 - 0x7FF)])
def test_sign_extend_fills_from_the_stated_bit(placed, expect):
    api = ImmApi(32)
    api.place(placed, 11, 0, at=0)
    api.sign_extend(from_bit=11)
    assert api.value & M32 == expect


def test_sign_extend_at_the_top_bit_fills_nothing():
    api = ImmApi(32)
    api.place(0xFFFFFFFF, 31, 0, at=0)
    api.sign_extend(from_bit=31)         # nothing above the sign to fill
    assert api.value & M32 == M32


def test_a_placement_past_the_immediate_is_refused():
    with pytest.raises(ValueError, match="runs past"):
        ImmApi(12).place(0xFFFFFFFF, 31, 20, at=8)
    with pytest.raises(ValueError, match="hi >= lo"):
        ImmApi(32).place(0, 4, 9)


# --- RV32I's rules, against the spec's own encoders ---------------------------
def _enc_i(v):   return (v & 0xFFF) << 20
def _enc_s(v):   o = v & 0xFFF; return ((o >> 5) << 25) | ((o & 0x1F) << 7)
def _enc_u(v):   return (v & 0xFFFFF) << 12
def _enc_b(o):
    o &= 0x1FFF
    return ((((o >> 12) & 1) << 31) | (((o >> 5) & 0x3F) << 25)
            | (((o >> 1) & 0xF) << 8) | (((o >> 11) & 1) << 7))
def _enc_j(o):
    o &= 0x1FFFFF
    return ((((o >> 20) & 1) << 31) | (((o >> 1) & 0x3FF) << 21)
            | (((o >> 11) & 1) << 20) | (((o >> 12) & 0xFF) << 12))


@pytest.mark.parametrize("rule,encode", [(R.imm_i, _enc_i), (R.imm_s, _enc_s)])
def test_the_twelve_bit_forms_round_trip_over_their_whole_range(rule, encode):
    for v in range(-2048, 2048):
        assert run(rule, encode(v)) == v & M32


def test_a_branch_offset_round_trips_over_its_whole_even_range():
    # imm_b is the scrambled one the naive assembly got wrong: four segments,
    # an implicit zero at bit 0, sign from bit 12.
    for off in range(-4096, 4096, 2):
        assert run(R.imm_b, _enc_b(off)) == off & M32


def test_a_jump_offset_round_trips_over_its_whole_even_range():
    for off in range(-(1 << 20), 1 << 20, 2):
        assert run(R.imm_j, _enc_j(off)) == off & M32


def test_a_u_type_lands_in_the_top_twenty_bits():
    # already signed in place: the field's top bit IS bit 31 of the value.
    for v in (0, 1, 0xFFFFF, 0x80000):
        assert run(R.imm_u, _enc_u(v)) == (v << 12) & M32


# --- how a rule reaches the engine --------------------------------------------
def test_every_scrambled_rv32i_immediate_states_its_rule():
    # the default cannot place segments, so anything multi-segment must.
    for operand in (OPR_IMM_I, OPR_IMM_S, OPR_IMM_B, OPR_IMM_U, OPR_IMM_J):
        assert operand.imm_extract is not None
    # shamt is the one case the default gets right: contiguous, zero-extended
    assert OPR_IMM_SHAMT.imm_extract is None


def test_extract_imm_value_runs_the_operands_own_rule():
    assert extract_imm_value(_enc_i(-5), OPR_IMM_I) & M32 == -5 & M32
    assert extract_imm_value(_enc_b(-8), OPR_IMM_B) & M32 == -8 & M32


def test_the_default_reads_a_single_contiguous_field():
    # shamt: word[24:20], zero-extended
    assert extract_imm_value(0b11111 << 20, OPR_IMM_SHAMT) == 0x1F


def test_a_scrambled_field_with_no_rule_is_refused():
    # the silent wrong answer the rule replaces: nothing says where the
    # segments land, so assembling them first-lowest would be a guess.
    atm = AtomicOperand(SRC, "src_3", intermediate=Intermediate(32, "imm"))
    opr = Operand(atm, IMM, matcher=FM.IMM_B)
    with pytest.raises(ValueError, match="states no imm_extract"):
        extract_imm_value(0, opr)


# --- what an extraction rule may sit on ---------------------------------------
def test_a_rule_needs_a_slot_that_names_an_immediate():
    x   = RegFile("x", 32, 32)
    atm = AtomicOperand(SRC, "src_1", reg_file=x)
    with pytest.raises(ValueError, match="names an immediate"):
        Operand(atm, ARCH, 0, matcher=FM.RS1, imm_extract=R.imm_i)


def test_a_rule_needs_a_matcher_saying_which_bits_it_reads():
    atm = AtomicOperand(SRC, "src_3", intermediate=Intermediate(32, "imm"))
    with pytest.raises(ValueError, match="no matcher"):
        Operand(atm, IMM, imm_extract=R.imm_i)


def test_a_rule_must_be_callable():
    atm = AtomicOperand(SRC, "src_3", intermediate=Intermediate(32, "imm"))
    with pytest.raises(TypeError, match="must be callable"):
        Operand(atm, IMM, matcher=FM.IMM_I, imm_extract=42)
