# InstrFieldMatch — where a named encoding field lives, and how two of them
# combine. The union cases are the usage documentation: RISC-V's add and sub
# share funct3 and differ only in funct7, so selecting either needs one rule
# spanning both fields. InstrValueMatch is the other half — what those bits
# must equal — and its cases are the same add-vs-sub pair, now actually
# distinguishable.

import pytest

from carolyne.isa import InstrFieldMatch, InstrValueMatch


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


def test_a_value_match_is_values_only():
    # No field: a value rule is a bit pattern, and which bits it is compared
    # against is stated by whatever pairs the two. One value per segment of
    # that field, in the same order, so add vs sub reads like the spec table.
    add = InstrValueMatch((0b000, 0b0000000))       # funct3, funct7
    sub = InstrValueMatch((0b000, 0b0100000))
    assert add.match_value == (0, 0) and sub.match_value == (0, 0b0100000)
    assert add != sub                       # what a bare field match cannot say
    assert not hasattr(add, "match_idx")    # the position half stays elsewhere


def test_values_are_validated_as_bit_patterns():
    assert InstrValueMatch((0b111,)).match_value == (7,)
    with pytest.raises(IndexError):
        InstrValueMatch(())                         # no values
    with pytest.raises(ValueError):
        InstrValueMatch((-1,))                      # a bit pattern, not a number
    with pytest.raises(TypeError):
        InstrValueMatch(("000",))                   # not an int

    # NOT checked here, and the gap is the point: with no field in the type,
    # nothing can say 0b1000 overflows a 3-bit funct3, or that two values were
    # given for a one-segment field. That check lands wherever the pairing does.
    assert InstrValueMatch((0b1000,)).match_value == (8,)


def test_value_union_runs_in_step_with_the_field_union():
    # The two unions are meant to be called in the same order, so segments and
    # values stay index-aligned across the merge.
    funct3, funct7 = InstrFieldMatch("funct3", ((12, 15),)), InstrFieldMatch("funct7", ((25, 32),))
    val3,   val7   = InstrValueMatch((0b101,)), InstrValueMatch((0b0100000,))

    field, value = funct3 | funct7, val3 | val7     # srl vs sra: funct7 decides
    assert field.match_idx == ((12, 15), (25, 32))
    assert value.match_value == (0b101, 0b0100000)
    assert len(value.match_value) == len(field.match_idx)

    # Same order rule as the field side: reversing gives a different rule.
    assert (val7 | val3).match_value == (0b0100000, 0b101)
    assert val3.union(val7, val3).match_value == (0b101, 0b0100000, 0b101)
    with pytest.raises(TypeError):
        val3.union(funct7)                          # field, not value
    with pytest.raises(TypeError):
        funct3.union(val7)                          # and the reverse


def test_the_holder_of_both_halves_checks_the_pairing():
    # Neither type can validate the other — a field does not know what values
    # test it, a value does not know its segments — so the holder does it.
    from carolyne.isa import Mop, Uop, UopSeq

    funct3, add = InstrFieldMatch("funct3", ((12, 15),)), "ADD"
    uop = Uop(add, 0, matcher_field=funct3, matcher_value=InstrValueMatch((0b000,)))
    assert uop.matcher_value.match_value == (0,)

    with pytest.raises(ValueError):                 # 4 bits into a 3-bit segment
        Uop(add, 0, matcher_field=funct3, matcher_value=InstrValueMatch((0b1000,)))
    with pytest.raises(ValueError):                 # 2 values, 1 segment
        Uop(add, 0, matcher_field=funct3, matcher_value=InstrValueMatch((0, 0)))
    with pytest.raises(ValueError):                 # nothing to test against
        Uop(add, 0, matcher_value=InstrValueMatch((0b000,)))

    # A field with no value is legal: positions stated, nothing tested yet.
    assert Uop(add, 0, matcher_field=funct3).matcher_value is None

    # The same check guards the other two holders.
    with pytest.raises(ValueError):
        UopSeq(uops=(Uop(add, 0),), matcher_value=InstrValueMatch((0,)))
    with pytest.raises(ValueError):
        Mop(matcher_field=funct3, matcher_value=InstrValueMatch((0b1000,)),
            uop_seq=(UopSeq(uops=(Uop(add, 0),)),))


def test_rv32i_uses_a_union_where_one_field_cannot_select():
    from carolyne.isa.riscv import field_match as FM, uop as U

    assert FM.FUNCT3_7.match_idx == FM.FUNCT3.match_idx + FM.FUNCT7.match_idx
    # add vs sub, srl vs sra, and the three shift-immediates need both fields.
    both = [u for u in U.UOPS if u.matcher_field is FM.FUNCT3_7]
    assert len(both) == 7
    assert U.UOP_ADD.matcher_field is FM.FUNCT3_7
    assert U.UOP_SLT.matcher_field is FM.FUNCT3
    # And the values make them actually distinguishable: same field, same
    # funct3, different funct7 — the pair the union exists for.
    assert U.UOP_ADD.matcher_value.match_value == (0b000, 0b0000000)
    assert U.UOP_SUB.matcher_value.match_value == (0b000, 0b0100000)
    assert U.UOP_ADD.matcher_field is U.UOP_SUB.matcher_field
    assert U.UOP_ADD != U.UOP_SUB
