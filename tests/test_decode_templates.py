# group_uops_by_level — the mop table flattened for decode's breadth-first
# walk: levels[k] holds the k-th µop of every crack, each with the WHOLE
# conjunction of rules that identifies its encoding.
#
# The match is checked in PURE PYTHON, by evaluating the same (field, value)
# tuples a decoder would compare. That tests what actually matters — that every
# RV32I encoding picks exactly one µop — without a simulator.

import pytest

from carolyne.isa import (ExecUnit, InstrFieldMatch, InstrValueMatch, IsaBase,
                          Mop, Uop, UopSeq)
from carolyne.isa.riscv import Rv32i, uop as U
from carolyne.uarch.o3.decode import group_uops_by_level

ISA    = Rv32i()
X      = ISA.reg_file("x")
LEVELS = group_uops_by_level(ISA)


# --- the match tree, evaluated on real encodings -------------------------------
def _hits(word: int, level: int = 0) -> list:
    """Every µop whose rules hold for this instruction word, at one level."""
    return [uop for matchers, uop in LEVELS[level]
            if all(((word >> start) & ((1 << (end - start)) - 1)) == want
                   for field, value in matchers
                   for (start, end), want in zip(field.match_idx, value.match_value))]


def _word(opcode, rd=0, funct3=0, rs1=0, rs2=0, funct7=0) -> int:
    return (opcode | rd << 7 | funct3 << 12 | rs1 << 15 | rs2 << 20 | funct7 << 25)


def test_every_encoding_picks_exactly_one_uop():
    # What makes the guards safe: the conditions are mutually exclusive, so
    # mop_decode lays one INDEPENDENT zif per path and needs no priority
    # between them.
    cases = {
        "add x1,x2,x3" : (_word(0b0110011, rd=1, funct3=0b000, rs1=2, rs2=3),
                          U.UOP_ADD),
        "sub x1,x2,x3" : (_word(0b0110011, rd=1, funct3=0b000, rs1=2, rs2=3,
                                funct7=0b0100000), U.UOP_SUB),
        "addi x1,x2,5" : (_word(0b0010011, rd=1, funct3=0b000, rs1=2) | 5 << 20,
                          U.UOP_ADDI),
        "srai x1,x2,3" : (_word(0b0010011, rd=1, funct3=0b101, rs1=2,
                                funct7=0b0100000) | 3 << 20, U.UOP_SRAI),
        "lw x1,0(x2)"  : (_word(0b0000011, rd=1, funct3=0b010, rs1=2), U.UOP_LW),
        "sw x3,0(x2)"  : (_word(0b0100011, funct3=0b010, rs1=2, rs2=3), U.UOP_SW),
        "beq x1,x2"    : (_word(0b1100011, funct3=0b000, rs1=1, rs2=2), U.UOP_BEQ),
        "lui x1,0x1000": (_word(0b0110111, rd=1) | 0x1000 << 12, U.UOP_LUI),
        "jal x1"       : (_word(0b1101111, rd=1), U.UOP_JAL),
        "ecall"        : (_word(0b1110011, funct3=0b000), U.UOP_ECALL),
        "ebreak"       : (_word(0b1110011, funct3=0b000) | 1 << 20, U.UOP_EBREAK),
    }
    for asm, (word, want) in cases.items():
        picked = _hits(word)
        assert len(picked) == 1, f"{asm}: {[u.name for u in picked]}"
        assert picked[0] is want, asm


def test_an_unknown_encoding_matches_nothing():
    # No hit at a level means the lane keeps write_lane_default's valid=0 —
    # the bubble, one priority rung below every matched branch.
    assert _hits(_word(0b0000000)) == []      # opcode no group claims
    assert _hits(_word(0b0110011, funct3=0b000, funct7=0b1111111)) == []


def test_rv32i_reaches_every_uop_in_one_level():
    # Every RV32I instruction is exactly ONE µop: no AGU, no CALL_LINK, so
    # nothing cracks and the walk is a single cycle.
    assert len(LEVELS) == 1
    reached = [uop for _matchers, uop in LEVELS[0]]
    assert len(reached) == len(ISA.uops) == 40
    assert {id(u) for u in reached} == {id(u) for u in ISA.uops}


def test_uop_idx_is_declared_and_covers_the_vocabulary():
    # The id the whole core speaks after decode: DECLARED on the template, so
    # reordering UOPS cannot silently renumber the emitted hardware.
    reached = [uop for _matchers, uop in LEVELS[0]]
    assert sorted(u.uop_idx for u in reached) == list(range(len(ISA.uops)))
    assert ISA.uop("ADD").uop_idx == U.UOP_ADD.uop_idx


def test_a_uop_carries_every_rule_on_its_path():
    # The mop's bits AND the uop_seq's: add and sub share an opcode and differ
    # only in funct7, so both rules ride on the path. A template itself carries
    # no matcher — the encoding side owns them.
    by_name = {uop.name: matchers for matchers, uop in LEVELS[0]}
    assert {f.name for f, _v in by_name["SUB"]} == {"opcode", "funct3+funct7"}
    # LUI's opcode alone identifies it, so its path carries the mop's rule only.
    assert [f.name for f, _v in by_name["LUI"]] == ["opcode"]


# --- cracking -------------------------------------------------------------------
def test_a_crack_becomes_one_level_per_uop():
    # x86's AGU->LOAD->ADD->STORE is this shape: decode walks the sequence
    # breadth-first, one LEVEL per cycle, and every level carries the SAME
    # conjunction so the identity cannot drift mid-crack.
    agu, load = Uop("AGU", 0), Uop("LOAD", 1)
    unit      = ExecUnit("agu_mem", (agu, load))
    field     = InstrFieldMatch("op", ((0, 7),))
    isa       = IsaBase(name="cracker", pc_width=32, pc_align=4, ilen_bytes=4,
                        reg_files=(X,), atomic_operands=ISA.atomic_operands,
                        operands=ISA.operands, exec_units=(unit,),
                        uops=(agu, load),
                        mops=(Mop(matcher_field=field,
                                  matcher_value=InstrValueMatch((0b1111111,)),
                                  uop_seq=(UopSeq(uops=(agu, load)),)),))

    levels = group_uops_by_level(isa)
    assert len(levels) == 2
    assert [uop for _m, uop in levels[0]] == [agu]
    assert [uop for _m, uop in levels[1]] == [load]
    # the same guard at both levels
    assert levels[0][0][0] == levels[1][0][0]


# --- refusals -------------------------------------------------------------------
def test_a_path_with_no_rule_at_all_is_refused():
    # Positions stated, nothing tested: the encoding cannot be told from its
    # neighbours', so there is no guard to build a zif from.
    uop  = Uop("ADD", 0)
    unit = ExecUnit("alu", (uop,))
    with pytest.raises(ValueError, match="no \\(field, value\\) rule"):
        group_uops_by_level(
            IsaBase(name="ruleless", pc_width=32, pc_align=4, ilen_bytes=4,
                    reg_files=(X,), atomic_operands=ISA.atomic_operands,
                    operands=ISA.operands, exec_units=(unit,), uops=(uop,),
                    mops=(Mop(matcher_field=InstrFieldMatch("op", ((0, 7),)),
                              uop_seq=(UopSeq(uops=(uop,)),)),)))
