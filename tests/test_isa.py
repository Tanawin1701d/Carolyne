# IsaBase — the container a generator is handed: the ISA's register classes,
# op vocabulary, the machine's exec units, and the mops binding encodings to
# µop sequences. The first test is the usage documentation (a two-instruction
# toy ISA); the rest pin the cross-checks that make the container worth
# having — notably "a mop names an op the ISA never declared", which is the
# validation that went missing when Uop dropped its `unit` field.

import pytest

from carolyne.isa import (
    ExecUnit, FieldRef, InstrFieldMatch, IsaBase, Mop, Op, Operand,
    OperandRole, RegFile, Uop, UopSeq,
)

SRC, DEST = OperandRole.SRC, OperandRole.DEST

ADD  = Op("ADD")
LOAD = Op("LOAD")

ALU = ExecUnit("alu", {ADD})
MEM = ExecUnit("mem", {LOAD})

X     = RegFile("x", 32, 32, const_regs={0: 0})
FLAGS = RegFile("flags", 6, 1)


def _mop(op, opcode, reg_file=X):
    # One encoding → one µop sequence. (Field binding is still preliminary:
    # the matcher is a single InstrFieldMatch on the opcode bits.)
    uop = Uop(op,
              srcs=(Operand(reg_file, SRC, FieldRef("rs1")),),
              dests=(Operand(reg_file, DEST, FieldRef("rd")),))
    return Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
               uop_seq=(UopSeq(uops=(uop,), matcher_field=InstrFieldMatch(opcode, ((0, 7),))),))


def _isa(**overrides):
    kwargs = dict(name="toy", reg_files=(X,), ops=(ADD, LOAD),
                  exec_units=(ALU, MEM), mops=(_mop(ADD, "add"), _mop(LOAD, "lw")))
    kwargs.update(overrides)
    return IsaBase(**kwargs)


def test_isa_holds_the_vocabularies():
    isa = _isa()
    assert isa.op("ADD") is ADD and isa.unit("mem") is MEM
    assert isa.reg_file("x") is X
    assert isa.used_ops() == {ADD, LOAD}
    assert isa.used_reg_files() == (X,)
    # Routing is read out of the unit set, not stamped into the µops.
    assert isa.units_for(ADD) == (ALU,)
    with pytest.raises(ValueError):
        isa.op("ADQ")                       # unknown name fails loudly
    with pytest.raises(ValueError):
        isa.unit("crypto")
    with pytest.raises(ValueError):
        isa.reg_file("gpr")


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


def test_a_mop_may_not_target_an_undeclared_reg_file():
    # Same rule for register classes: the elaborator sizes one PRF/RAT per
    # declared file, so a class only some crack knows about would be missed.
    with pytest.raises(ValueError, match="register file 'flags'"):
        _isa(mops=(_mop(ADD, "add", reg_file=FLAGS),))


def test_reg_files_are_matched_by_identity():
    # An equal-but-different RegFile is a *second* class to the elaborator,
    # so declaring a twin does not satisfy the check.
    twin = RegFile("x", 32, 32, const_regs={0: 0})
    assert twin == X                        # value-equal...
    with pytest.raises(ValueError, match="does not declare"):
        _isa(reg_files=(twin,))             # ...but not the instance the µops target


def test_every_declared_op_needs_a_unit_that_executes_it():
    with pytest.raises(ValueError, match="no exec unit executes"):
        _isa(exec_units=(ALU,))             # nothing runs LOAD


def test_a_unit_may_list_ops_this_isa_never_uses():
    # The reverse direction is allowed on purpose, so one ExecUnit definition
    # can be shared across ISAs.
    big_alu = ExecUnit("alu", {ADD, Op("SUB"), Op("XOR")})
    isa = _isa(exec_units=(big_alu, MEM))
    assert isa.used_ops() == {ADD, LOAD}


def test_declared_but_unused_reg_file_is_fine():
    # x86 FLAGS declared before any crack writes it, say — declaring more
    # than the mops use is not an error, the reverse is.
    isa = _isa(reg_files=(X, FLAGS))
    assert isa.reg_file("flags") is FLAGS and isa.used_reg_files() == (X,)


def test_isa_validation():
    with pytest.raises(ValueError):
        _isa(name="")                       # unnamed ISA
    with pytest.raises(ValueError):
        _isa(mops=())                       # empty vocabulary
    with pytest.raises(ValueError):
        _isa(reg_files=())
    with pytest.raises(TypeError):
        _isa(ops=(ADD, "LOAD"))             # a string is not an Op
    with pytest.raises(TypeError):
        _isa(reg_files=(X, "flags"))
    with pytest.raises(ValueError, match="duplicate"):
        _isa(exec_units=(ALU, ExecUnit("alu", {LOAD})))
    with pytest.raises(ValueError, match="duplicate"):
        _isa(reg_files=(X, RegFile("x", 8, 4)))


def test_a_per_isa_package_may_subclass_it():
    # IsaBase is a base: a package with extra description fields subclasses
    # it (staying frozen, staying data), otherwise a factory returning
    # IsaBase is the plain way.  See the isa.py header.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class ToyIsa(IsaBase):
        prefixes : tuple = ()

    isa = ToyIsa(name="toy", reg_files=(X,), ops=(ADD, LOAD),
                 exec_units=(ALU, MEM), mops=(_mop(ADD, "add"), _mop(LOAD, "lw")),
                 prefixes=("0x66",))
    assert isa.prefixes == ("0x66",) and isa.op("ADD") is ADD
    with pytest.raises(ValueError):         # inherited checks still run
        ToyIsa(name="", reg_files=(X,), ops=(ADD,), exec_units=(ALU,),
               mops=(_mop(ADD, "add"),))
