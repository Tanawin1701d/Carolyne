# IsaDescription — the container a generator is handed: the ISA's op
# vocabulary, the machine's exec units, and the mops binding encodings to µop
# sequences. The first test is the usage documentation (a two-instruction
# toy ISA); the rest pin the cross-checks that make the container worth
# having — notably "a mop names an op the ISA never declared", which is the
# validation that went missing when Uop dropped its `unit` field.

import pytest

from carolyne.isa import (
    ExecUnit, FieldRef, InstrFieldMatch, IsaDescription, Mop, Op, Operand,
    RegFile, Uop, UopSeq,
)

ADD  = Op("ADD")
LOAD = Op("LOAD")

ALU = ExecUnit("alu", {ADD})
MEM = ExecUnit("mem", {LOAD})

X = RegFile("x", 32, 32, const_regs={0: 0})


def _mop(op, opcode):
    # One encoding → one µop sequence. (Field binding is still preliminary:
    # the matcher is a single InstrFieldMatch on the opcode bits.)
    uop = Uop(op,
              srcs=(Operand(X, FieldRef("rs1")),),
              dests=(Operand(X, FieldRef("rd")),))
    return Mop(matcher=InstrFieldMatch("opcode", ((0, 7),)),
               uop_seq=(UopSeq(uops=(uop,), matcher=InstrFieldMatch(opcode, ((0, 7),))),))


def _isa(**overrides):
    kwargs = dict(name="toy", ops=(ADD, LOAD), exec_units=(ALU, MEM),
                  mops=(_mop(ADD, "add"), _mop(LOAD, "lw")))
    kwargs.update(overrides)
    return IsaDescription(**kwargs)


def test_isa_holds_the_three_vocabularies():
    isa = _isa()
    assert isa.op("ADD") is ADD and isa.unit("mem") is MEM
    assert isa.used_ops() == {ADD, LOAD}
    # Routing is read out of the unit set, not stamped into the µops.
    assert isa.units_for(ADD) == (ALU,)
    with pytest.raises(ValueError):
        isa.op("ADQ")                       # unknown name fails loudly
    with pytest.raises(ValueError):
        isa.unit("crypto")


def test_an_op_may_be_claimed_by_several_units():
    # Two ALUs is a machine-configuration choice, not a description error:
    # the elaborator picks which one issues a given µop.
    alu2 = ExecUnit("alu2", {ADD})
    isa  = _isa(exec_units=(ALU, alu2, MEM))
    assert [u.name for u in isa.units_for(ADD)] == ["alu", "alu2"]


def test_a_mop_may_not_use_an_undeclared_op():
    # The check that replaces Uop's old op-vs-unit validation: a typo'd op
    # reaches the container, and the container is what refuses it.
    with pytest.raises(ValueError, match="does not declare"):
        _isa(mops=(_mop(ADD, "add"), _mop(Op("ADQ"), "adq")))


def test_every_declared_op_needs_a_unit_that_executes_it():
    with pytest.raises(ValueError, match="no exec unit executes"):
        _isa(exec_units=(ALU,))             # nothing runs LOAD


def test_a_unit_may_list_ops_this_isa_never_uses():
    # The reverse direction is allowed on purpose, so one ExecUnit definition
    # can be shared across ISAs.
    big_alu = ExecUnit("alu", {ADD, Op("SUB"), Op("XOR")})
    isa = _isa(exec_units=(big_alu, MEM))
    assert isa.used_ops() == {ADD, LOAD}


def test_isa_validation():
    with pytest.raises(ValueError):
        _isa(name="")                       # unnamed ISA
    with pytest.raises(ValueError):
        _isa(mops=())                       # empty vocabulary
    with pytest.raises(TypeError):
        _isa(ops=(ADD, "LOAD"))             # a string is not an Op
    with pytest.raises(ValueError, match="duplicate"):
        _isa(exec_units=(ALU, ExecUnit("alu", {LOAD})))
