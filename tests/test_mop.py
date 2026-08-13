# Layout + Mop: the encoding metadata that binds an instruction layout to the
# µop sequence(s) it cracks into (uop_contract.md §1.3 + §1.4). The two big
# tests are the usage documentation — the RISC-V R-type family (one layout,
# many variants, one µop each) and x86 `add [mem], reg` (one variant, a 4-µop
# sequence) — i.e. the two directions of the list-of-lists.

import pytest

from carolyne.isa import (
    ALU, MEM,
    Field, FieldRef, Intermediate, Layout, Mop, Operand, RegFile, Uop, Variant,
)


# --------------------------------------------------------------------------
# Field / Layout


def test_field_widths_and_splits():
    assert Field("rd", (11, 7)).width == 5              # bare pair -> one segment
    assert not Field("rd", (11, 7)).is_split
    # RISC-V B-type immediate: scattered, MSB-first concatenation.
    imm_b = Field("imm_b", ((31, 31), (7, 7), (30, 25), (11, 8)), signed=True)
    assert imm_b.width == 12 and imm_b.is_split and imm_b.signed
    with pytest.raises(ValueError):
        Field("bad", (7, 11))                           # hi < lo
    with pytest.raises(ValueError):
        Field("bad", ((11, 7), (9, 8)))                 # segments overlap


def test_layout_rejects_self_contradiction():
    fields = {"rd": (11, 7), "rs1": (19, 15)}
    ok = Layout(32, match=0b0110011, mask=0x7f, fields=fields)
    assert ok.field_names == ("rd", "rs1") and ok.field("rd").width == 5
    assert ok.matches(0b0110011) and not ok.matches(0b0010011)
    with pytest.raises(ValueError):
        Layout(32, match=0xff, mask=0x7f, fields=fields)        # match bits outside mask
    with pytest.raises(ValueError):
        Layout(32, match=0b0110011, mask=0xfff, fields=fields)  # mask swallows rd
    with pytest.raises(ValueError):
        Layout(8, match=0x1, mask=0x1, fields=fields)           # field outside the word


# --------------------------------------------------------------------------
# The RISC-V direction: one layout, many variants (the outer list)

X       = RegFile("x", 32, 32, const_regs={0: 0})
R_TYPE  = Layout(32, match=0b0110011, mask=0x7f,
                 fields={"rd": (11, 7), "rs1": (19, 15), "rs2": (24, 20),
                         "funct3": (14, 12), "funct7": (31, 25)})


def _rtype(op):
    # The per-ISA factory function: one shape, the op passed in (uop.py).
    return (Uop(ALU, op,
                srcs=(Operand(X, FieldRef("rs1")), Operand(X, FieldRef("rs2"))),
                dests=(Operand(X, FieldRef("rd")),)),)


def _rtype_mop():
    return Mop("R-TYPE", R_TYPE, (
        Variant({"funct3": 0x0, "funct7": 0x00}, _rtype("ADD")),
        Variant({"funct3": 0x0, "funct7": 0x20}, _rtype("SUB")),
        Variant({"funct3": 0x7, "funct7": 0x00}, _rtype("AND")),
    ))


def test_riscv_rtype_family_shares_one_layout():
    mop = _rtype_mop()
    assert mop.is_family and mop.max_uops == 1
    # rd/rs1/rs2 positions are declared ONCE, ops differ per variant.
    assert [v.uops[0].op for v in mop.variants] == ["ADD", "SUB", "AND"]
    assert all(v.uops[0].srcs == mop.variants[0].uops[0].srcs for v in mop.variants)


def test_riscv_rtype_decodes_to_the_right_variant():
    mop = _rtype_mop()
    # add x1, x2, x3 / sub x1, x2, x3 — same fields, funct7 apart.
    add = 0b0000000_00011_00010_000_00001_0110011
    sub = 0b0100000_00011_00010_000_00001_0110011
    assert mop.select(add).uops[0].op == "ADD"
    assert mop.select(sub).uops[0].op == "SUB"
    with pytest.raises(KeyError):
        mop.select(0b0000000_00011_00010_001_00001_0110011)  # funct3=1: no variant
    with pytest.raises(KeyError):
        mop.select(0b0010011)                                # not this layout at all


def test_split_field_extracts_msb_first():
    # RISC-V B-type immediate: imm[12|10:5] and imm[4:1|11] live apart in the
    # word, so the segments concatenate MSB-first to imm[12|11|10:5|4:1].
    layout = Layout(32, match=0b1100011, mask=0x7f,
                    fields={"imm_b": Field("imm_b", ((31, 31), (7, 7), (30, 25), (11, 8)),
                                           signed=True)})
    mop = Mop("BRANCH", layout, (Variant({}, (Uop(ALU, "ADD", imm=FieldRef("imm_b")),)),))
    # Set exactly one instruction bit per segment and check where it lands.
    assert mop.extract(1 << 31, "imm_b") == 1 << 11         # segment 0 -> top bit
    assert mop.extract(1 <<  7, "imm_b") == 1 << 10         # segment 1 -> next
    assert mop.extract(1 << 25, "imm_b") == 1 <<  4         # segment 2 -> bits 9..4
    assert mop.extract(1 <<  8, "imm_b") == 1               # segment 3 -> bits 3..0
    assert layout.field("imm_b").width == 12


def test_single_uop_variant_is_both_first_and_last():
    # §2 `bound`: a 1-µop instruction is first AND last, so commit retires it
    # on its own (§4.4).
    variant = _rtype_mop().variants[0]
    assert variant.bounds == ((True, True),) and not variant.is_cracked


# --------------------------------------------------------------------------
# The x86 direction: one variant, a multi-µop sequence (the inner list)

GPR   = RegFile("gpr", 32, 8)
FLAGS = RegFile("flags", 6, 1)
X86   = Layout(32, match=0x01, mask=0xff,
               fields={"modrm_reg": (13, 11), "modrm_rm": (10, 8),
                       "mod": (15, 14), "disp": Field("disp", (31, 16), signed=True)})


def _mem_add_uops():
    addr, old, new = Intermediate(32, "addr"), Intermediate(32, "old"), Intermediate(32, "new")
    return (
        Uop(MEM, "AGU",   srcs=(Operand(GPR, FieldRef("modrm_rm")),),
                          dests=(Operand(addr),), imm=FieldRef("disp")),
        Uop(MEM, "LOAD",  srcs=(Operand(addr),), dests=(Operand(old),)),
        Uop(ALU, "ADD",   srcs=(Operand(old), Operand(GPR, FieldRef("modrm_reg"))),
                          dests=(Operand(new), Operand(FLAGS, 0))),
        Uop(MEM, "STORE", srcs=(Operand(addr), Operand(new))),
    )


def test_x86_mem_add_is_one_variant_of_four_uops():
    # The contract's flagship crack (§1.4) as a Mop: `add [m], r` (mod != 11)
    # takes 4 µops, the register form takes 1 — two variants, one layout.
    mop = Mop("ADD", X86, (
        Variant({"mod": 0b10}, _mem_add_uops()),
        Variant({"mod": 0b11}, (Uop(ALU, "ADD",
                                    srcs=(Operand(GPR, FieldRef("modrm_rm")),
                                          Operand(GPR, FieldRef("modrm_reg"))),
                                    dests=(Operand(GPR, FieldRef("modrm_rm")),
                                           Operand(FLAGS, 0))),)),
    ))
    assert mop.max_uops == 4
    mem = mop.variants[0]
    assert mem.is_cracked
    assert [u.op for u in mem.uops] == ["AGU", "LOAD", "ADD", "STORE"]
    # §2 `bound` / §4.4: only the AGU is `first`, only the STORE is `last`, so
    # the whole 4-µop crack commits all-or-nothing.
    assert mem.bounds == ((True, False), (False, False), (False, False), (False, True))


# --------------------------------------------------------------------------
# Validation: the checks that make a bad ISA description fail loudly


def test_mop_checks_field_refs_against_the_layout():
    # The check field_ref.py deferred to this layer: a FieldRef is just a name
    # until a cracker is bound to an encoding.
    thin = Layout(32, match=0b0110011, mask=0x7f, fields={"rd": (11, 7), "rs1": (19, 15)})
    with pytest.raises(ValueError, match="rs2"):
        Mop("R-TYPE", thin, (Variant({}, _rtype("ADD")),))       # rs2 undeclared


def test_mop_checks_the_discriminator():
    with pytest.raises(ValueError, match="funct9"):
        Mop("R", R_TYPE, (Variant({"funct9": 0}, _rtype("ADD")),))   # no such field
    with pytest.raises(ValueError, match="does not fit"):
        Mop("R", R_TYPE, (Variant({"funct3": 0x9}, _rtype("ADD")),))  # 3-bit field, 4-bit value


def test_mop_rejects_ambiguous_variants():
    same = (Variant({"funct3": 0}, _rtype("ADD")), Variant({"funct3": 0}, _rtype("SUB")))
    with pytest.raises(ValueError, match="not distinguishable"):
        Mop("R", R_TYPE, same)
    # A subset is just as ambiguous: funct3=0 alone also matches funct3=0,funct7=0.
    subset = (Variant({"funct3": 0}, _rtype("ADD")),
              Variant({"funct3": 0, "funct7": 0}, _rtype("SUB")))
    with pytest.raises(ValueError, match="not distinguishable"):
        Mop("R", R_TYPE, subset)


def test_variant_enforces_utemp_discipline():
    addr, old = Intermediate(32, "addr"), Intermediate(32, "old")
    with pytest.raises(ValueError, match="before any earlier µop writes it"):
        Variant({}, (Uop(MEM, "LOAD", srcs=(Operand(addr),), dests=(Operand(old),)),
                     Uop(MEM, "AGU",  srcs=(Operand(GPR, FieldRef("modrm_rm")),),
                                      dests=(Operand(addr),)),))     # AGU too late
    with pytest.raises(ValueError, match="written but never read"):
        Variant({}, (Uop(MEM, "AGU", srcs=(Operand(GPR, FieldRef("modrm_rm")),),
                                     dests=(Operand(addr),)),))      # addr goes nowhere
    with pytest.raises(ValueError, match="rewrites µtemp"):
        Variant({}, (Uop(MEM, "AGU",  srcs=(Operand(GPR, 1),), dests=(Operand(addr),)),
                     Uop(MEM, "AGU",  srcs=(Operand(GPR, 2),), dests=(Operand(addr),)),
                     Uop(MEM, "LOAD", srcs=(Operand(addr),), dests=(Operand(old),)),
                     Uop(MEM, "STORE", srcs=(Operand(addr), Operand(old))),))
    with pytest.raises(ValueError, match="at least one"):
        Variant({}, ())                                              # empty sequence
