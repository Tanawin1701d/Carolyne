# IsaBase — the container a generator is handed: the ISA's register classes,
# op vocabulary, the machine's exec units, and the mops binding encodings to
# µop sequences. The first test is the usage documentation (a two-instruction
# toy ISA); the rest pin the cross-checks that make the container worth
# having — notably "a mop names an op the ISA never declared", which is the
# validation that went missing when Uop dropped its `unit` field.

import pytest

from carolyne.isa import (
    AtomicOperand, ExecUnit, FieldRef, InstrFieldMatch, IsaBase, Mop, Op,
    Operand, OperandRole, RegFile, TargetKind, Uop, UopSeq,
)

SRC, DEST  = OperandRole.SRC, OperandRole.DEST
ARCH, TEMP = TargetKind.ARCH, TargetKind.TEMP

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
              srcs=(Operand(AtomicOperand(SRC, reg_file=reg_file), ARCH, FieldRef("rs1")),),
              dests=(Operand(AtomicOperand(DEST, reg_file=reg_file), ARCH, FieldRef("rd")),))
    return Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
               uop_seq=(UopSeq(uops=(uop,), matcher_field=InstrFieldMatch(opcode, ((0, 7),))),))


def _walk(mops):
    """The uops/operands/cores a set of mops actually uses, in order.

    A real package declares these from its own module constants (see
    riscv/rv32i.py); this toy builds its shapes inside _mop, so the default
    declaration is read back off the mops. Tests that pin the cross-checks
    override one vocabulary with something the mops do not use.
    """
    uops     = tuple(u for mop in mops for seq in mop.uop_seq for u in seq.uops)
    operands = tuple(o for u in uops for o in u.srcs + u.dests)
    return uops, operands, tuple(o.atomic for o in operands)


def _isa(**overrides):
    mops = overrides.pop("mops", (_mop(ADD, "add"), _mop(LOAD, "lw")))
    uops, operands, cores = _walk(mops)
    kwargs = dict(name="toy", reg_files=(X,), atomic_operands=cores,
                  operands=operands, ops=(ADD, LOAD), exec_units=(ALU, MEM),
                  uops=uops, mops=mops)
    kwargs.update(overrides)
    return IsaBase(**kwargs)


def test_isa_holds_the_vocabularies():
    isa = _isa()
    assert isa.op("ADD") is ADD and isa.unit("mem") is MEM
    assert isa.reg_file("x") is X
    assert isa.used_ops() == {ADD, LOAD}
    assert isa.used_reg_files() == (X,)
    # Two mops, one µop each, two operands per µop, one core per operand.
    assert len(isa.used_uops()) == 2
    assert len(isa.used_operands()) == 4 and len(isa.used_atomic_operands()) == 4
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


def test_a_mop_may_not_use_an_undeclared_uop():
    # The chain is checked one link at a time: a µop riding inside a mop is
    # not thereby part of the ISA.
    other = Uop(ADD)
    with pytest.raises(ValueError, match="does not declare in uops"):
        _isa(uops=(other,))


def test_a_mop_may_not_use_an_undeclared_operand_or_core():
    core  = AtomicOperand(SRC, reg_file=X)
    spare = Operand(core, ARCH, FieldRef("rs1"))
    with pytest.raises(ValueError, match="does not declare in operands"):
        _isa(operands=(spare,))
    with pytest.raises(ValueError, match="does not declare in atomic_operands"):
        _isa(atomic_operands=(core,))


def test_operands_are_matched_by_identity_not_equality():
    # An equal-but-separate rule is what the identity match exists to catch:
    # a package shares operand constants so every template naming rs1 names
    # ONE object, and a crack that quietly rebuilt it has drifted.
    mops = (_mop(ADD, "add"),)
    _, operands, _ = _walk(mops)
    twin = Operand(operands[0].atomic, operands[0].target_kind,
                   operands[0].index, operands[0].matcher)

    assert twin == operands[0] and twin is not operands[0]
    with pytest.raises(ValueError, match="does not declare in operands"):
        _isa(mops=mops, operands=(twin,) + operands[1:])


def test_a_vocabulary_may_not_list_one_instance_twice():
    # No names to key on, so a duplicate is the same object listed twice.
    mops = (_mop(ADD, "add"),)
    uops, operands, cores = _walk(mops)
    with pytest.raises(ValueError, match="same object twice"):
        _isa(mops=mops, uops=uops + uops)
    # ...while value-equal twins are two legitimate slots.
    assert _isa(mops=mops, atomic_operands=cores + (AtomicOperand(SRC, reg_file=X),))


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


def test_declared_but_unused_operands_and_uops_are_fine_too():
    # Same direction as the reg-file rule: a package may write a rule down
    # before a crack uses it.
    mops = (_mop(ADD, "add"),)
    uops, operands, cores = _walk(mops)
    spare_core = AtomicOperand(DEST, reg_file=FLAGS)
    isa = _isa(mops=mops,
               atomic_operands=cores + (spare_core,),
               operands=operands + (Operand(spare_core, ARCH),),
               uops=uops + (Uop(LOAD),))
    assert len(isa.uops) == len(isa.used_uops()) + 1
    assert len(isa.operands) == len(isa.used_operands()) + 1


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

    mops = (_mop(ADD, "add"), _mop(LOAD, "lw"))
    uops, operands, cores = _walk(mops)
    isa = ToyIsa(name="toy", reg_files=(X,), atomic_operands=cores,
                 operands=operands, ops=(ADD, LOAD), exec_units=(ALU, MEM),
                 uops=uops, mops=mops, prefixes=("0x66",))
    assert isa.prefixes == ("0x66",) and isa.op("ADD") is ADD
    with pytest.raises(ValueError):         # inherited checks still run
        ToyIsa(name="", reg_files=(X,), atomic_operands=cores, operands=operands,
               ops=(ADD,), exec_units=(ALU,), uops=uops, mops=mops)
