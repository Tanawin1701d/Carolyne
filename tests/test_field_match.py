# InstrFieldMatch — where a named encoding field lives, and how two of them
# combine. The union cases are the usage documentation: RISC-V's add and sub
# share funct3 and differ only in funct7, so selecting either needs one rule
# spanning both fields.

import pytest

from carolyne.isa import InstrFieldMatch


def test_segments_are_validated_at_construction():
    assert InstrFieldMatch("opcode", ((0, 7),)).width == 7
    with pytest.raises(IndexError):
        InstrFieldMatch("empty", ())                    # no segments
    with pytest.raises(IndexError):
        InstrFieldMatch("bare", (0, 7))                 # a pair, not a tuple of pairs
    with pytest.raises(IndexError):
        InstrFieldMatch("backwards", ((7, 0),))         # start >= end


def test_union_spans_both_fields():
    funct3 = InstrFieldMatch("funct3", ((12, 15),))
    funct7 = InstrFieldMatch("funct7", ((25, 32),))

    both = funct3.union(funct7)
    assert both.match_idx == ((12, 15), (25, 32))
    assert both.name == "funct3+funct7" and both.width == 10
    assert funct3.union(funct7, name="funct").name == "funct"


def test_union_appends_in_the_order_given():
    # No sorting: segment order is the caller's statement about the field, so
    # a | b and b | a are different rules, not the same one normalized.
    funct3 = InstrFieldMatch("funct3", ((12, 15),))
    funct7 = InstrFieldMatch("funct7", ((25, 32),))
    assert (funct7 | funct3).match_idx == ((25, 32), (12, 15))
    assert (funct7 | funct3).name == "funct7+funct3"


def test_union_takes_more_than_two():
    a = InstrFieldMatch("a", ((0, 4),))
    b = InstrFieldMatch("b", ((8, 12),))
    c = InstrFieldMatch("c", ((4, 8),))
    assert a.union(b, c).match_idx == ((0, 4), (8, 12), (4, 8))


def test_union_neither_merges_nor_rejects_segments():
    # Adjacent stays adjacent (imm_b's (7,8) is imm[11], (8,12) is imm[4:1]),
    # and overlap is the caller's business — union only appends.
    imm_b = InstrFieldMatch("imm_b", ((7, 8), (8, 12)))
    other = InstrFieldMatch("hi", ((25, 31),))
    assert imm_b.union(other).match_idx == ((7, 8), (8, 12), (25, 31))

    funct3 = InstrFieldMatch("funct3", ((12, 15),))
    assert funct3.union(funct3).match_idx == ((12, 15), (12, 15))
    with pytest.raises(TypeError):                  # a non-field still raises
        funct3.union("funct7")


def test_rv32i_uses_a_union_where_one_field_cannot_select():
    from carolyne.isa.riscv import field_match as FM, uop as U

    assert FM.FUNCT3_7.match_idx == FM.FUNCT3.match_idx + FM.FUNCT7.match_idx
    # add vs sub, srl vs sra, and the three shift-immediates need both fields.
    both = [u for u in U.UOPS if u.matcher is FM.FUNCT3_7]
    assert len(both) == 7
    assert U.UOP_ADD.matcher is FM.FUNCT3_7 and U.UOP_SLT.matcher is FM.FUNCT3
