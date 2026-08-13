# ExecUnit catalog + Uop template validation. The later tests are the usage
# documentation: a RISC-V addi, the family-as-factory-function pattern, and
# the x86 `add [mem], reg` 4-µop crack from the contract doc, now as real
# Uop templates (the operand-only version of the same shape lives in
# test_operand.py).

import pytest

from carolyne.isa import (
    ALU, CONTROL, MEM, SYSTEM, STANDARD_UNITS,
    ExecUnit, FieldRef, Intermediate, Operand, RegFile, Uop,
)


def test_standard_catalog_is_contract_owned():
    # Mirrors uop_contract.md §1.2 — spot checks, not a copy of the table.
    assert ALU.has("ADD") and ALU.has("MOV_IMM")
    assert MEM.ops == {"AGU", "LOAD", "STORE"}
    assert CONTROL.has("BR_COND") and SYSTEM.has("TRAP")
    assert len({u.name for u in STANDARD_UNITS}) == 5


def test_exec_unit_validation():
    # A custom FU is just another ExecUnit instance an ISA declares.
    crypto = ExecUnit("crypto", {"AES_ROUND"})
    assert crypto.has("AES_ROUND")
    with pytest.raises(ValueError):
        ExecUnit("", {"X"})                     # unnamed unit
    with pytest.raises(ValueError):
        ExecUnit("empty", set())                # unit with nothing to do
    with pytest.raises(ValueError):
        ExecUnit("bad", {""})                   # empty op name


def test_uop_validates_op_against_unit():
    x = RegFile("x", 32, 32, const_regs={0: 0})
    rd, rs1, rs2 = (Operand(x, FieldRef(f)) for f in ("rd", "rs1", "rs2"))
    add = Uop(ALU, "ADD", srcs=(rs1, rs2), dests=(rd,))
    assert add.unit is ALU and add.imm is None
    with pytest.raises(ValueError):
        Uop(ALU, "ADQ", srcs=(rs1, rs2), dests=(rd,))   # typo fails at construction
    with pytest.raises(ValueError):
        Uop(MEM, "ADD", srcs=(rs1, rs2), dests=(rd,))   # right op, wrong unit
    with pytest.raises(TypeError):
        Uop("alu", "ADD")                               # unit must be the object


def test_uop_capped_at_record_shape():
    # The template may not describe what the §2 record cannot carry.
    x  = RegFile("x", 32, 32)
    op = Operand(x, FieldRef("rs1"))
    assert Uop(ALU, "ADD", srcs=[op]).srcs == (op,)     # lists are normalized
    with pytest.raises(ValueError):
        Uop(ALU, "ADD", srcs=(op, op, op, op))          # > 3 sources
    with pytest.raises(ValueError):
        Uop(ALU, "ADD", dests=(op, op, op))             # > 2 dests
    with pytest.raises(TypeError):
        Uop(ALU, "ADD", srcs=(op, "rs2"))               # not an Operand
    with pytest.raises(TypeError):
        Uop(ALU, "ADD", imm="imm")                      # bare string is not a rule


def test_riscv_addi_uses_extracted_imm():
    # imm as a FieldRef: the value arrives from the decoder's field extractor.
    x = RegFile("x", 32, 32, const_regs={0: 0})
    addi = Uop(ALU, "ADD",
               srcs=(Operand(x, FieldRef("rs1")),),
               dests=(Operand(x, FieldRef("rd")),),
               imm=FieldRef("imm12"))
    assert addi.imm == FieldRef("imm12")


def test_riscv_rtype_family_is_a_factory_function():
    # `op` stays a single concrete string (see uop.py header). A family
    # differing only in the operation is a plain function the per-ISA package
    # defines; the encoding-table row passes the op, so every Uop reaching
    # the elaborator is already resolved.
    x = RegFile("x", 32, 32, const_regs={0: 0})

    def rtype(op):
        return (Uop(ALU, op,
                    srcs=(Operand(x, FieldRef("rs1")), Operand(x, FieldRef("rs2"))),
                    dests=(Operand(x, FieldRef("rd")),)),)

    add, sub = rtype("ADD"), rtype("SUB")
    assert (add[0].op, sub[0].op) == ("ADD", "SUB")
    assert add[0].srcs == sub[0].srcs                # one shared shape
    with pytest.raises(ValueError):
        rtype("ADQ")                                 # typo still fails at construction


def test_x86_push_bakes_constant_imm():
    # push reg: the -4 ESP adjustment is the cracker's constant (never in the
    # encoding), and ESP itself (index 4) is the ISA's implicit register.
    gpr     = RegFile("gpr", 32, 8)
    esp_new = Intermediate(32, "esp_new")
    dec = Uop(ALU, "ADD", srcs=(Operand(gpr, 4),), dests=(Operand(esp_new),), imm=-4)
    assert dec.imm == -4 and not dec.srcs[0].is_decoded


def test_x86_mem_add_cracks_to_four_uops():
    # add [base+disp], reg — the contract's flagship example (§1.4):
    # AGU→addr, LOAD addr→old, ADD old,reg→new+flags, STORE new@addr,
    # linked by shared Intermediate instances.
    gpr   = RegFile("gpr", 32, 8)
    flags = RegFile("flags", 6, 1)
    addr, old, new = Intermediate(32, "addr"), Intermediate(32, "old"), Intermediate(32, "new")

    crack = (
        Uop(MEM, "AGU",   srcs=(Operand(gpr, FieldRef("modrm_rm")),),
                          dests=(Operand(addr),), imm=FieldRef("disp")),
        Uop(MEM, "LOAD",  srcs=(Operand(addr),), dests=(Operand(old),)),
        Uop(ALU, "ADD",   srcs=(Operand(old), Operand(gpr, FieldRef("modrm_reg"))),
                          dests=(Operand(new), Operand(flags, 0))),
        Uop(MEM, "STORE", srcs=(Operand(addr), Operand(new))),
    )

    # The shared µtemp instance IS the dataflow link between the µops.
    assert crack[0].dests[0].target is crack[1].srcs[0].target is crack[3].srcs[0].target
    assert crack[1].dests[0].target is crack[2].srcs[0].target
    assert crack[2].dests[1].target is flags        # implicit 2nd dest: flags write
    assert all(u.unit in (MEM, ALU) for u in crack)
