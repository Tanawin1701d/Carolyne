# AtomicOperand — the irreducible core of an operand: which value, which
# direction, nothing else. These tests are the usage documentation for what
# the core does and does not know, and for the composition that makes every
# Operand hold one.

import pytest

from carolyne.isa import (
    AtomicOperand, FieldRef, Intermediate, Operand, OperandRole, RegFile)

SRC, DEST = OperandRole.SRC, OperandRole.DEST


def test_atomic_operand_is_the_pair_alone():
    x    = RegFile("x", 32, 32, const_regs={0: 0})
    addr = Intermediate(32, "addr")

    rd = AtomicOperand(x, DEST)
    assert rd.is_arch and rd.is_dest and not rd.is_src and rd.width == 32

    tmp = AtomicOperand(addr, SRC)
    assert tmp.is_intermediate and tmp.is_src and tmp.width == 32
    assert str(SRC) == "src" and str(DEST) == "dest"


def test_the_core_knows_nothing_about_an_index():
    # No is_const and no is_decoded here, though Operand has both: each is a
    # fact about the INDEX. Whether a slot is hardwired depends on WHICH
    # register of the class it names; whether it is decoded depends on where
    # that index comes from. The core has neither, so it answers neither.
    x    = RegFile("x", 32, 32, const_regs={0: 0})
    core = AtomicOperand(x, SRC)

    assert not hasattr(core, "index")
    assert not hasattr(core, "is_const")
    assert not hasattr(core, "is_decoded")
    # The same core serves x0 and x5 — it cannot tell them apart, and the
    # Operand built on it is what does.
    assert Operand(core, 0).is_const and not Operand(core, 5).is_const


def test_atomic_operand_validation():
    x = RegFile("x", 32, 32)
    with pytest.raises(TypeError):
        AtomicOperand(x, "src")             # the word is not the role
    with pytest.raises(TypeError):
        AtomicOperand("x", SRC)             # not a RegFile/Intermediate
    # A multi-register class is FINE here — the core says nothing about
    # indexing, and 30 of RV32I's 37 operands target exactly this file. An
    # earlier version refused it; see the atomic_operand.py header.
    assert AtomicOperand(x, SRC).is_arch


def test_every_operand_is_built_on_one():
    # Composition, not inheritance: Operand is not substitutable for its core
    # (it demands an index rule the core knows nothing about), so it holds one
    # and forwards target/role rather than inheriting them.
    x    = RegFile("x", 32, 32)
    core = AtomicOperand(x, DEST)
    op   = Operand(core, FieldRef("rd"))

    assert op.atomic is core
    assert not isinstance(op, AtomicOperand)
    assert (op.target, op.role) == (core.target, core.role)
    assert op.is_dest and op.is_arch and op.width == core.width
    # Value equality, so one core is shared across every rule that needs it.
    assert AtomicOperand(x, DEST) == core


def test_cores_are_shared_across_the_rv32i_table():
    # riscv/operand.py builds three cores and hangs nine rules off them; the
    # rules differ where they actually differ — the field, and its bits.
    from carolyne.isa.riscv import OPR_IMMS, OPR_RD, OPR_RS1, OPR_RS2

    assert OPR_RS1.atomic is OPR_RS2.atomic          # same (x, SRC) core
    assert OPR_RD.atomic is not OPR_RS1.atomic       # different direction
    assert len({id(i.atomic) for i in OPR_IMMS}) == 1
    assert OPR_RS1.index != OPR_RS2.index            # ...and differ by field
