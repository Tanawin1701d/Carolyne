# Op / ExecUnit + Uop template validation. The later tests are the usage
# documentation: the family-as-factory-function pattern and the x86
# `add [mem], reg` 4-µop crack from the contract doc, as real Uop templates
# (the operand-only version of the same shape lives in test_operand.py).
#
# NOTE: the immediate rule (`Uop.imm`, FieldRef vs cracker-baked int) is not
# covered here any more — the field is out of Uop while the encoding-side
# InstrFieldMatch/matcher design is in flight. Restore the imm cases (RISC-V
# addi's imm12, x86 push's -4) once that lands.

import pytest

from carolyne.isa import (
    ExecUnit, FieldRef, Intermediate, Op, Operand, OperandRole, RegFile, Uop,
)

SRC, DEST = OperandRole.SRC, OperandRole.DEST

# No catalog ships with the isa layer (exec_unit.py header): a description
# declares the ops and units its machine has. This block is what a per-ISA
# package writes — the uop_contract.md §1.2 names are a convention, not an
# import.
ADD   = Op("ADD")
SUB   = Op("SUB")
AGU   = Op("AGU")
LOAD  = Op("LOAD")
STORE = Op("STORE")

ALU = ExecUnit("alu", {ADD, SUB})
MEM = ExecUnit("mem", {AGU, LOAD, STORE})


def test_op_is_an_object_with_value_equality():
    # Re-spelling an op yields the SAME op — otherwise two description files
    # naming ADD would build µops no unit recognizes as each other's.
    assert Op("ADD") == ADD and hash(Op("ADD")) == hash(ADD)
    assert ADD != SUB and str(ADD) == "ADD"
    with pytest.raises(ValueError):
        Op("")                                  # nameless op


def test_exec_unit_validation():
    # A custom FU is just another ExecUnit instance an ISA declares, and its
    # ops are as first-class as an ADD.
    aes_round = Op("AES_ROUND")
    crypto = ExecUnit("crypto", {aes_round})
    assert crypto.has(aes_round) and crypto.op("AES_ROUND") is aes_round
    with pytest.raises(ValueError):
        crypto.op("AES_KEY")                    # unknown name, loud lookup
    with pytest.raises(ValueError):
        ExecUnit("", {ADD})                     # unnamed unit
    with pytest.raises(ValueError):
        ExecUnit("empty", set())                # unit with nothing to do
    with pytest.raises(TypeError):
        ExecUnit("bad", {"ADD"})                # a string is not an Op


def test_op_routing_lives_in_the_unit_set_not_the_uop():
    # A Uop names only what it does. WHICH unit executes it is a machine
    # configuration question the unit set answers (ExecUnit.ops read the
    # other way round), so two units may both claim the same ADD.
    vec   = ExecUnit("vec", {ADD, SUB})
    units = (ALU, MEM, vec)
    x     = RegFile("x", 32, 32)

    add = Uop(ADD, srcs=(Operand(x, SRC, FieldRef("rs1")),))
    assert add.op is ADD
    assert [u.name for u in units if u.has(add.op)] == ["alu", "vec"]


def test_uop_requires_an_op_object():
    x = RegFile("x", 32, 32, const_regs={0: 0})
    rd = Operand(x, DEST, FieldRef("rd"))
    rs1, rs2 = (Operand(x, SRC, FieldRef(f)) for f in ("rs1", "rs2"))
    add = Uop(ADD, srcs=(rs1, rs2), dests=(rd,))
    assert add.op is ADD
    with pytest.raises(TypeError):
        Uop("ADD", srcs=(rs1, rs2), dests=(rd,))   # op must be the object
    # A made-up op is NOT caught here (no unit to check against); it is
    # caught when no unit of the machine claims it.
    assert not any(u.has(Op("ADQ")) for u in (ALU, MEM))


def test_uop_capped_at_record_shape():
    # The template may not describe what the §2 record cannot carry.
    x  = RegFile("x", 32, 32)
    op = Operand(x, SRC, FieldRef("rs1"))
    assert Uop(ADD, srcs=[op]).srcs == (op,)       # lists are normalized
    with pytest.raises(ValueError):
        Uop(ADD, srcs=(op, op, op, op))            # > 3 sources
    with pytest.raises(ValueError):
        Uop(ADD, dests=(Operand(x, DEST, FieldRef("rd")),) * 3)   # > 2 dests
    with pytest.raises(TypeError):
        Uop(ADD, srcs=(op, "rs2"))                 # not an Operand


def test_uop_holds_operand_role_to_its_position():
    # srcs/dests state the direction positionally and the operand states it
    # itself; Uop is the one place that sees both, so it is where they are
    # held to each other. Without this the redundancy would be a bug source.
    x   = RegFile("x", 32, 32)
    src = Operand(x, SRC,  FieldRef("rs1"))
    dst = Operand(x, DEST, FieldRef("rd"))
    assert Uop(ADD, srcs=(src,), dests=(dst,)).dests[0].is_dest
    with pytest.raises(ValueError):
        Uop(ADD, srcs=(dst,))               # a dest operand in the src list
    with pytest.raises(ValueError):
        Uop(ADD, srcs=(src,), dests=(src,))  # ...and the other way round


def test_encoding_text_becomes_an_op_through_the_unit():
    # An encoding table row names its op as text; unit.op() is the sanctioned
    # (and loudly failing) way in, so no string ever reaches a Uop.
    x = RegFile("x", 32, 32, const_regs={0: 0})
    row_op = ALU.op("SUB")
    assert row_op is SUB
    assert Uop(row_op, srcs=(Operand(x, SRC, FieldRef("rs1")),)).op is SUB


def test_riscv_rtype_family_is_a_factory_function():
    # `op` stays a single concrete Op (see uop.py header). A family differing
    # only in the operation is a plain function the per-ISA package defines;
    # the encoding-table row passes the op, so every Uop reaching the
    # elaborator is already resolved.
    x = RegFile("x", 32, 32, const_regs={0: 0})

    def rtype(op):
        return (Uop(op,
                    srcs=(Operand(x, SRC, FieldRef("rs1")), Operand(x, SRC, FieldRef("rs2"))),
                    dests=(Operand(x, DEST, FieldRef("rd")),)),)

    add, sub = rtype(ADD), rtype(SUB)
    assert (add[0].op, sub[0].op) == (ADD, SUB)
    assert add[0].srcs == sub[0].srcs                # one shared shape


def test_x86_implicit_register_operand():
    # push reg: ESP (index 4) is the ISA's implicit register, never decoded.
    # (The -4 adjustment rides in the imm rule — see the NOTE at the top.)
    gpr     = RegFile("gpr", 32, 8)
    esp_new = Intermediate(32, "esp_new")
    dec = Uop(ADD, srcs=(Operand(gpr, SRC, 4),), dests=(Operand(esp_new, DEST),))
    assert not dec.srcs[0].is_decoded       # literal index, not is_const: ESP isn't hardwired


def test_x86_mem_add_cracks_to_four_uops():
    # add [base+disp], reg — the contract's flagship example (§1.4):
    # AGU→addr, LOAD addr→old, ADD old,reg→new+flags, STORE new@addr,
    # linked by shared Intermediate instances.
    gpr   = RegFile("gpr", 32, 8)
    flags = RegFile("flags", 6, 1)
    addr, old, new = Intermediate(32, "addr"), Intermediate(32, "old"), Intermediate(32, "new")

    crack = (
        Uop(AGU,   srcs=(Operand(gpr, SRC, FieldRef("modrm_rm")),),
                   dests=(Operand(addr, DEST),)),
        Uop(LOAD,  srcs=(Operand(addr, SRC),), dests=(Operand(old, DEST),)),
        Uop(ADD,   srcs=(Operand(old, SRC), Operand(gpr, SRC, FieldRef("modrm_reg"))),
                   dests=(Operand(new, DEST), Operand(flags, DEST, 0))),
        Uop(STORE, srcs=(Operand(addr, SRC), Operand(new, SRC))),
    )

    # The shared µtemp instance IS the dataflow link between the µops.
    assert crack[0].dests[0].target is crack[1].srcs[0].target is crack[3].srcs[0].target
    assert crack[1].dests[0].target is crack[2].srcs[0].target
    assert crack[2].dests[1].target is flags        # implicit 2nd dest: flags write
    # Routing is read off the unit set, not off the templates.
    assert all(MEM.has(u.op) or ALU.has(u.op) for u in crack)
