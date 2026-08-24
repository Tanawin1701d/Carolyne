# ExecUnit + Uop template validation. A µop NAMES ITSELF — there is no Op type
# between the template and its name — and a unit lists the templates it runs,
# by instance. The later tests are the usage
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
    AtomicOperand, ExecUnit, FieldRef, Intermediate, Operand, OperandRole,
    RegFile, TargetKind, Uop,
)

SRC, DEST  = OperandRole.SRC, OperandRole.DEST
ARCH, TEMP = TargetKind.ARCH, TargetKind.TEMP

# No catalog ships with the isa layer (exec_unit.py header): a description
# declares the µops and units its machine has. This block is what a per-ISA
# package writes — the uop_contract.md §1.2 names are a convention, not an
# import.
ADD   = Uop("ADD",   0)
SUB   = Uop("SUB",   1)
AGU   = Uop("AGU",   2)
LOAD  = Uop("LOAD",  3)
STORE = Uop("STORE", 4)

ALU = ExecUnit("alu", (ADD, SUB))
MEM = ExecUnit("mem", (AGU, LOAD, STORE))


def test_a_uop_names_itself_and_a_unit_lists_the_instance():
    # The template IS the kind: it carries its own name, and the hardware
    # plane speaks that vocabulary as uop_idx. Membership is by IDENTITY, the
    # discipline the whole layer runs on — a re-spelt template is a DIFFERENT
    # µop, so a unit lists the same constants the ISA declares.
    assert ADD.name == "ADD" and str(ADD) == "ADD"
    assert ALU.has(ADD) and not ALU.has(Uop("ADD", 0))
    with pytest.raises(ValueError):
        Uop("", 0)                              # nameless µop


def test_a_uop_declares_its_own_id():
    # uop_idx is DECLARED on the template, never read off a tuple position —
    # IsaBase holds the SET unique and dense; the template only answers for
    # its own value being a legal one.
    assert ADD.uop_idx == 0 and STORE.uop_idx == 4
    with pytest.raises(TypeError):
        Uop("ADD", "0")                         # an id is an int
    with pytest.raises(TypeError):
        Uop("ADD", True)                        # a bool is not an id
    with pytest.raises(ValueError):
        Uop("ADD", -1)                          # never negative


def test_exec_unit_validation():
    # A custom FU is just another ExecUnit instance an ISA declares, and its
    # µops are as first-class as an ADD.
    aes_round = Uop("AES_ROUND", 0)
    crypto = ExecUnit("crypto", (aes_round,))
    assert crypto.has(aes_round) and crypto.uop("AES_ROUND") is aes_round
    with pytest.raises(ValueError):
        crypto.uop("AES_KEY")                   # unknown name, loud lookup
    with pytest.raises(ValueError):
        ExecUnit("", (ADD,))                    # unnamed unit
    with pytest.raises(ValueError):
        ExecUnit("empty", ())                   # unit with nothing to do
    with pytest.raises(TypeError):
        ExecUnit("bad", ("ADD",))               # a string is not a Uop
    with pytest.raises(ValueError):
        ExecUnit("twice", (ADD, ADD))           # one template, listed once
    with pytest.raises(ValueError):
        ExecUnit("clash", (ADD, Uop("ADD", 9)))  # two µops cannot share a name


def test_routing_lives_in_the_unit_set_not_the_uop():
    # A Uop names only what it does. WHICH unit executes it is a machine
    # configuration question the unit set answers (ExecUnit.uops read the
    # other way round), so two units may both claim the same ADD.
    vec   = ExecUnit("vec", (ADD, SUB))
    units = (ALU, MEM, vec)

    assert [u.name for u in units if u.has(ADD)] == ["alu", "vec"]


def test_a_uop_needs_a_name_and_no_unit_vouches_for_it():
    x = RegFile("x", 32, 32, const_regs={0: 0})
    rd = Operand(AtomicOperand(DEST, reg_file=x), ARCH, FieldRef("rd"))
    rs1, rs2 = (Operand(AtomicOperand(SRC, reg_file=x), ARCH, FieldRef(f)) for f in ("rs1", "rs2"))
    add = Uop("ADD", 0, srcs=(rs1, rs2), dests=(rd,))
    assert add.name == "ADD"
    with pytest.raises(ValueError):
        Uop(123, 0, srcs=(rs1, rs2), dests=(rd,))  # a name is text
    # A made-up µop is NOT caught here (no unit to check against); it is
    # caught when no unit of the machine claims it.
    assert not any(u.has(Uop("ADQ", 0)) for u in (ALU, MEM))


def test_uop_capped_at_record_shape():
    # The template may not describe what the §2 record cannot carry.
    x  = RegFile("x", 32, 32)
    op = Operand(AtomicOperand(SRC, reg_file=x), ARCH, FieldRef("rs1"))
    assert Uop("ADD", 0, srcs=[op]).srcs == (op,)    # lists are normalized
    with pytest.raises(ValueError):
        Uop("ADD", 0, srcs=(op, op, op, op))         # > 3 sources
    with pytest.raises(ValueError):
        Uop("ADD", 0, dests=(Operand(AtomicOperand(DEST, reg_file=x), ARCH, FieldRef("rd")),) * 3)   # > 2 dests
    with pytest.raises(TypeError):
        Uop("ADD", 0, srcs=(op, "rs2"))              # not an Operand


def test_uop_holds_operand_role_to_its_position():
    # srcs/dests state the direction positionally and the operand states it
    # itself; Uop is the one place that sees both, so it is where they are
    # held to each other. Without this the redundancy would be a bug source.
    x   = RegFile("x", 32, 32)
    src = Operand(AtomicOperand(SRC, reg_file=x), ARCH,  FieldRef("rs1"))
    dst = Operand(AtomicOperand(DEST, reg_file=x), ARCH, FieldRef("rd"))
    assert Uop("ADD", 0, srcs=(src,), dests=(dst,)).dests[0].is_dest
    with pytest.raises(ValueError):
        Uop("ADD", 0, srcs=(dst,))            # a dest operand in the src list
    with pytest.raises(ValueError):
        Uop("ADD", 0, srcs=(src,), dests=(src,))  # ...and the other way round


def test_uop_slots_take_an_operand_and_nothing_else():
    # A µop template always states its index rule, so a slot is an Operand
    # full stop. AtomicOperand is a sibling type, not an alternative here —
    # admitting a union would make every consumer downstream ask which kind
    # it got before it could read one.
    flags = RegFile("flags", 6, 1)
    with pytest.raises(TypeError):
        Uop("ADD", 0, dests=(AtomicOperand(flags, DEST),))
    with pytest.raises(TypeError):
        Uop("ADD", 0, srcs=(flags,))           # a RegFile is not an operand either


def test_encoding_text_reaches_a_template_through_the_unit():
    # An encoding table row names its µop as text; unit.uop() is the
    # sanctioned (and loudly failing) way in, and it hands back the INSTANCE
    # the unit runs — which is what identity membership needs.
    row_uop = ALU.uop("SUB")
    assert row_uop is SUB
    assert ALU.has(row_uop)


def test_riscv_rtype_family_is_a_factory_function():
    # A family differing only in the operation is a plain function the per-ISA
    # package defines; each call builds its own template, named for what it
    # does, so every Uop reaching the elaborator is already resolved.
    x = RegFile("x", 32, 32, const_regs={0: 0})

    def rtype(name, uop_idx):
        return (Uop(name, uop_idx,
                    srcs=(Operand(AtomicOperand(SRC, reg_file=x), ARCH, FieldRef("rs1")), Operand(AtomicOperand(SRC, reg_file=x), ARCH, FieldRef("rs2"))),
                    dests=(Operand(AtomicOperand(DEST, reg_file=x), ARCH, FieldRef("rd")),)),)

    add, sub = rtype("ADD", 0), rtype("SUB", 1)
    assert (add[0].name, sub[0].name) == ("ADD", "SUB")
    assert add[0].srcs == sub[0].srcs                # one shared shape


def test_x86_implicit_register_operand():
    # push reg: ESP (index 4) is the ISA's implicit register, never decoded.
    # (The -4 adjustment rides in the imm rule — see the NOTE at the top.)
    gpr     = RegFile("gpr", 32, 8)
    esp_new = Intermediate(32, "esp_new")
    dec = Uop("ADD", 0, srcs=(Operand(AtomicOperand(SRC, reg_file=gpr), ARCH, 4),), dests=(Operand(AtomicOperand(DEST, intermediate=esp_new), TEMP),))
    assert not dec.srcs[0].is_decoded       # literal index, not is_const: ESP isn't hardwired


def test_x86_mem_add_cracks_to_four_uops():
    # add [base+disp], reg — the contract's flagship example (§1.4):
    # AGU→addr, LOAD addr→old, ADD old,reg→new+flags, STORE new@addr,
    # linked by shared Intermediate instances.
    gpr   = RegFile("gpr", 32, 8)
    flags = RegFile("flags", 6, 1)
    addr, old, new = Intermediate(32, "addr"), Intermediate(32, "old"), Intermediate(32, "new")

    crack = (
        Uop("AGU",   0, srcs=(Operand(AtomicOperand(SRC, reg_file=gpr), ARCH, FieldRef("modrm_rm")),),
                   dests=(Operand(AtomicOperand(DEST, intermediate=addr), TEMP),)),
        Uop("LOAD",  1, srcs=(Operand(AtomicOperand(SRC, intermediate=addr), TEMP),), dests=(Operand(AtomicOperand(DEST, intermediate=old), TEMP),)),
        Uop("ADD",   2, srcs=(Operand(AtomicOperand(SRC, intermediate=old), TEMP), Operand(AtomicOperand(SRC, reg_file=gpr), ARCH, FieldRef("modrm_reg"))),
                   dests=(Operand(AtomicOperand(DEST, intermediate=new), TEMP), Operand(AtomicOperand(DEST, reg_file=flags), ARCH, 0))),
        Uop("STORE", 3, srcs=(Operand(AtomicOperand(SRC, intermediate=addr), TEMP), Operand(AtomicOperand(SRC, intermediate=new), TEMP))),
    )

    # The shared µtemp instance IS the dataflow link between the µops.
    assert crack[0].dests[0].target is crack[1].srcs[0].target is crack[3].srcs[0].target
    assert crack[1].dests[0].target is crack[2].srcs[0].target
    assert crack[2].dests[1].target is flags        # implicit 2nd dest: flags write
    # Routing is read off the unit set, not off the templates — and by
    # instance, so the units name the very templates the crack is built from.
    mem_unit = ExecUnit("x86_mem", (crack[0], crack[1], crack[3]))
    alu_unit = ExecUnit("x86_alu", (crack[2],))
    assert all(mem_unit.has(u) or alu_unit.has(u) for u in crack)
