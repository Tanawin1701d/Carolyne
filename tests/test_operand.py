# Intermediate identity semantics + Operand linking/validation. The last test
# is the x86 `add [mem], reg` cracking shape from the contract doc — operands
# threading arch regs and µtemps through a 4-µop template.

import pytest

from carolyne.isa import RegFile, Intermediate, FieldRef, Operand, OperandRole

SRC, DEST = OperandRole.SRC, OperandRole.DEST


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
    rd = Operand(x, DEST, FieldRef("rd"))
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
    op = Operand(x, SRC, 5)
    assert op.is_arch and not op.is_decoded
    assert Operand(x, SRC, 0).is_const and not op.is_const   # x0 hardwired
    with pytest.raises(ValueError):
        Operand(x, SRC)                     # missing index rule
    with pytest.raises(ValueError):
        Operand(x, SRC, 32)                 # literal out of range
    with pytest.raises(TypeError):
        Operand(x, SRC, "rd")               # bare string is not an index rule
    with pytest.raises(TypeError):
        Operand("x", SRC, 5)                # not a RegFile/Intermediate


def test_operand_states_its_own_role():
    # The role is what lets an operand handed around ALONE — to a rename-port
    # list, to a record slot — still say which direction it flows. It is a
    # closed set (contract §2 has only src and dest slots), hence an enum,
    # unlike Op; and there is no SRC_DEST, because a read-modify-written arch
    # slot is genuinely two record slots and two rename ports.
    x = RegFile("x", 32, 32)
    assert Operand(x, SRC, 5).is_src and Operand(x, DEST, 5).is_dest
    assert str(SRC) == "src" and str(DEST) == "dest"
    with pytest.raises(TypeError):
        Operand(x, "src", 5)                # the word is not the role
    with pytest.raises(TypeError):
        Operand(x, index=5)                 # role is required, never defaulted


def test_intermediate_operand_carries_no_index():
    t = Intermediate(32, "addr")
    op = Operand(t, DEST)
    assert op.is_intermediate and op.width == 32
    with pytest.raises(ValueError):
        Operand(t, DEST, 0)                 # index forbidden on a µtemp


def test_x86_mem_add_cracking_shape():
    # add [base+disp], reg  ->  AGU -> LOAD -> ADD -> STORE, linked by shared
    # Intermediate instances. Just the operand plumbing — µop templates come later.
    gpr   = RegFile("gpr", 32, 8)
    flags = RegFile("flags", 6, 1)
    addr  = Intermediate(32, "addr")
    old   = Intermediate(32, "old")
    new   = Intermediate(32, "new")

    agu_dst   = Operand(addr, DEST)
    load_src  = Operand(addr, SRC)          # same node: LOAD consumes AGU's result
    load_dst  = Operand(old,  DEST)
    add_srcs  = (Operand(old, SRC), Operand(gpr, SRC, FieldRef("modrm_reg")))  # decoded reg
    add_dsts  = (Operand(new, DEST), Operand(flags, DEST, 0))  # 2nd dest: implicit flags write
    store_src = Operand(new, SRC)

    assert agu_dst.target is load_src.target        # the link IS the shared node
    assert agu_dst.is_dest and load_src.is_src      # ...read in opposite directions
    assert add_dsts[1].width == 6                   # flags operand sized by its file
    assert store_src.is_intermediate
