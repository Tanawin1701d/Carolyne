# Intermediate identity semantics + Operand linking/validation. The last test
# is the x86 `add [mem], reg` cracking shape from the contract doc — operands
# threading arch regs and µtemps through a 4-µop template.

import pytest

from carolyne.isa import (
    AtomicOperand, FieldRef, Intermediate, Operand, OperandRole, RegFile, TargetKind)

SRC, DEST  = OperandRole.SRC, OperandRole.DEST
ARCH, TEMP = TargetKind.ARCH, TargetKind.TEMP


def test_intermediate_identity_not_equality():
    a, b = Intermediate(32), Intermediate(32)
    assert a is not b and a != b            # same width, distinct value nodes
    assert len({a: 0, b: 1}) == 2           # usable as distinct dict keys
    with pytest.raises(ValueError):
        Intermediate(0)


def test_decoded_operand_uses_field_ref():
    # The normal case: the register index arrives at runtime from an encoding
    # field. The template only names the field — no value is locked in.
    x  = RegFile("x", 32, 32, const_regs={0: 0})
    rd = Operand(AtomicOperand(DEST, reg_file=x), ARCH, FieldRef("rd"))
    assert rd.is_arch and rd.is_decoded
    assert rd.is_dest and not rd.is_src
    assert rd.width == 32
    assert not rd.is_const                  # may hit x0 at runtime; rename's job
    assert FieldRef("rd") == FieldRef("rd") # equality by name within a template
    with pytest.raises(ValueError):
        FieldRef("")


def test_implicit_operand_uses_literal_index():
    # Implicit fixed registers ARE part of the ISA (x86 push/pop -> ESP).
    x = RegFile("x", 32, 32, const_regs={0: 0})
    op = Operand(AtomicOperand(SRC, reg_file=x), ARCH, 5)
    assert op.is_arch and not op.is_decoded
    assert Operand(AtomicOperand(SRC, reg_file=x), ARCH, 0).is_const and not op.is_const   # x0 hardwired
    with pytest.raises(ValueError):
        Operand(AtomicOperand(SRC, reg_file=x), ARCH)                     # missing index rule
    with pytest.raises(ValueError):
        Operand(AtomicOperand(SRC, reg_file=x), ARCH, 32)                 # literal out of range
    with pytest.raises(TypeError):
        Operand(AtomicOperand(SRC, reg_file=x), ARCH, "rd")               # bare string is not an index rule
    with pytest.raises(TypeError):
        Operand(x, 5)                       # a bare target is not a core


def test_operand_is_built_on_an_atomic_core():
    # The role is the core's, forwarded. The TARGET is not: the core only
    # offers candidates, and target_kind is the slot's own statement of which
    # one it names — so target/width/is_arch are answered here, not there.
    x    = RegFile("x", 32, 32)
    core = AtomicOperand(SRC, reg_file=x)
    op   = Operand(core, ARCH, 5)

    assert op.atomic is core
    assert op.role is core.role and op.is_src and not op.is_dest
    assert op.target is x and op.width == 32 and op.is_arch
    assert not hasattr(core, "target") and not hasattr(core, "width")
    with pytest.raises(TypeError):
        Operand(core)                       # the selector is required, never defaulted
    with pytest.raises(TypeError):
        Operand("rs1", ARCH, 5)             # the core must be an AtomicOperand
    with pytest.raises(ValueError, match="offers no temp"):
        Operand(core, TEMP)                 # ...and must carry what the slot selects


def test_index_may_be_omitted_only_on_a_one_register_class():
    # index_width 0 (x86 FLAGS): there is nothing to choose, so the rule is
    # allowed to say nothing and the elaborator wires the single register.
    # This is the surviving half of a check AtomicOperand briefly carried.
    flags = RegFile("flags", 6, 1, const_regs={0: 0})
    x     = RegFile("x", 32, 32)

    fl = Operand(AtomicOperand(DEST, reg_file=flags), ARCH)
    assert fl.index is None and not fl.is_decoded
    assert fl.is_const                      # the one register IS register 0
    with pytest.raises(ValueError, match="holds 32"):
        Operand(AtomicOperand(SRC, reg_file=x), ARCH)      # 32 registers: which one is a real question


def test_intermediate_operand_carries_no_index():
    t = Intermediate(32, "addr")
    op = Operand(AtomicOperand(DEST, intermediate=t), TEMP)
    assert op.is_intermediate and op.width == 32
    with pytest.raises(ValueError):
        Operand(AtomicOperand(DEST, intermediate=t), TEMP, 0)                 # index forbidden on a µtemp


def test_x86_mem_add_cracking_shape():
    # add [base+disp], reg  ->  AGU -> LOAD -> ADD -> STORE, linked by shared
    # Intermediate instances. Just the operand plumbing — µop templates come later.
    gpr   = RegFile("gpr", 32, 8)
    flags = RegFile("flags", 6, 1)
    addr  = Intermediate(32, "addr")
    old   = Intermediate(32, "old")
    new   = Intermediate(32, "new")

    agu_dst   = Operand(AtomicOperand(DEST, intermediate=addr), TEMP)
    load_src  = Operand(AtomicOperand(SRC, intermediate=addr), TEMP)   # same node: LOAD consumes AGU's result
    load_dst  = Operand(AtomicOperand(DEST, intermediate=old), TEMP)
    add_srcs  = (Operand(AtomicOperand(SRC, intermediate=old), TEMP),  # decoded reg beside the µtemp
                 Operand(AtomicOperand(SRC, reg_file=gpr), ARCH, FieldRef("modrm_reg")))
    add_dsts  = (Operand(AtomicOperand(DEST, intermediate=new), TEMP),
                 Operand(AtomicOperand(DEST, reg_file=flags), ARCH))   # 2nd dest: implicit flags
    store_src = Operand(AtomicOperand(SRC, intermediate=new), TEMP)

    assert agu_dst.target is load_src.target        # the link IS the shared node
    assert agu_dst.is_dest and load_src.is_src      # ...read in opposite directions
    assert add_dsts[1].width == 6                   # flags operand sized by its file
    assert add_dsts[1].index is None                # 1-reg class: nothing to choose
    assert store_src.is_intermediate
