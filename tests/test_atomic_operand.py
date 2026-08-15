# AtomicOperand — the core of an operand: the value(s) a slot may name and the
# direction it flows. These tests are the usage documentation for the two-target
# form and for the selection that resolves it, which lives on Operand.

import pytest

from carolyne.isa import (
    AtomicOperand, FieldRef, Intermediate, Operand, OperandRole, RegFile,
    TargetKind)

SRC, DEST  = OperandRole.SRC, OperandRole.DEST
ARCH, TEMP = TargetKind.ARCH, TargetKind.TEMP


def test_a_core_may_carry_one_target_or_both():
    x    = RegFile("x", 32, 32)
    addr = Intermediate(32, "addr")

    reg_only  = AtomicOperand(SRC, reg_file=x)
    temp_only = AtomicOperand(SRC, intermediate=addr)
    either    = AtomicOperand(SRC, reg_file=x, intermediate=addr)

    assert reg_only.has_arch and not reg_only.has_temp
    assert temp_only.has_temp and not temp_only.has_arch
    assert either.has_arch and either.has_temp
    assert either.target_for(ARCH) is x and either.target_for(TEMP) is addr


def test_a_core_must_name_at_least_one_value():
    with pytest.raises(ValueError, match="names no value"):
        AtomicOperand(SRC)
    with pytest.raises(TypeError):
        AtomicOperand("src", reg_file=RegFile("x", 32, 32))   # the word is not the role
    with pytest.raises(TypeError):
        AtomicOperand(SRC, reg_file=Intermediate(32))         # fields are not interchangeable
    with pytest.raises(TypeError):
        AtomicOperand(SRC, intermediate=RegFile("x", 32, 32))


def test_selecting_a_target_the_core_does_not_carry_is_refused():
    # A rule that selects what is not on offer is broken, not empty — and it
    # fails when the Operand is built, not later in a generator.
    x    = RegFile("x", 32, 32)
    core = AtomicOperand(SRC, reg_file=x)

    assert core.target_for(ARCH) is x
    with pytest.raises(ValueError, match="offers no temp"):
        core.target_for(TEMP)
    with pytest.raises(ValueError, match="offers no temp"):
        Operand(core, TEMP)
    with pytest.raises(TypeError):
        core.target_for("arch")                 # the word is not the kind


def test_one_core_can_serve_rules_that_resolve_differently():
    # The point of two targets: a single encoding slot that is a register in
    # one form and a loaded value in another (x86 ModRM r/m). One core, two
    # rules, each naming what IT selects.
    gpr  = RegFile("gpr", 32, 8)
    load = Intermediate(32, "loaded")
    core = AtomicOperand(SRC, reg_file=gpr, intermediate=load)

    as_reg = Operand(core, ARCH, FieldRef("modrm_rm"))
    as_mem = Operand(core, TEMP)

    assert as_reg.atomic is as_mem.atomic        # ...the same core
    assert as_reg.target is gpr and as_mem.target is load
    assert as_reg.is_arch and as_mem.is_intermediate
    assert as_reg.role is as_mem.role is SRC


def test_the_core_knows_nothing_about_an_index_or_a_width():
    # No is_const, no is_decoded, no width, no target: the first two are facts
    # about the INDEX, which the core has not got; the last two need the
    # SELECTION, since two candidates may differ in kind and in width.
    x    = RegFile("x", 32, 32, const_regs={0: 0})
    core = AtomicOperand(SRC, reg_file=x)

    for absent in ("index", "is_const", "is_decoded", "width", "target"):
        assert not hasattr(core, absent), absent
    # The same core serves x0 and x5 — the Operand built on it tells them apart.
    assert Operand(core, ARCH, 0).is_const and not Operand(core, ARCH, 5).is_const


def test_cores_are_shared_across_the_rv32i_table():
    # riscv/operand.py names one core per SLOT and hangs its rules off them.
    # Src slot 2 carries BOTH targets, so the register rule and four immediate
    # rules share one core and resolve it differently — the two-target form
    # exercised by a real ISA package, not just by the x86 shape above.
    from carolyne.isa.riscv import OPR_IMMS, OPR_IMM_I, OPR_RD, OPR_RS1, OPR_RS2

    shared = OPR_RS2.atomic
    assert OPR_IMM_I.atomic is shared and shared.has_arch and shared.has_temp
    assert OPR_RS2.target_kind is ARCH and OPR_IMM_I.target_kind is TEMP
    assert OPR_RS2.target is not OPR_IMM_I.target        # one core, two answers

    assert all(i.target_kind is TEMP for i in OPR_IMMS)
    assert OPR_RD.atomic is not OPR_RS1.atomic           # different direction
    assert OPR_RS1.atomic != OPR_RS2.atomic              # rs2's core offers more
    assert OPR_RS1.index != OPR_RS2.index                # ...and they read different fields
