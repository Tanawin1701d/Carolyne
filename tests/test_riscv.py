# The RV32I package as usage documentation for a per-ISA description: it
# declares its own register classes, ops, units and mop table, and hands the
# lot to IsaBase — which is what actually validates it. These tests pin the
# invariants a hand-written ISA package can get wrong, not the RISC-V spec.

import pytest

from carolyne.isa import (
    FieldRef, Intermediate, InstrFieldMatch, IsaBase, Operand)
from carolyne.isa.riscv import (
    ILEN_BYTES, ImmTarget, OPR_IMMS, OPR_RD, OPR_RS1, OPR_RS2, RegFile,
    field_match as FM, op as O, rv32i, x_file,
)


def _uops(isa, op=None):
    """Every µop of the table, optionally only those naming one op."""
    return [uop
            for mop in isa.mops for seq in mop.uop_seq for uop in seq.uops
            if op is None or uop.op is op]


def test_rv32i_builds_and_passes_the_container_checks():
    # Construction IS the test: IsaBase rejects an undeclared op, an
    # undeclared reg file, or an op no unit executes.
    isa = rv32i()
    assert isinstance(isa, IsaBase) and isa.name == "rv32i"
    assert isa.reg_file("x").amount == 32 and isa.reg_file("x").is_const(0)
    assert isa.used_ops() <= set(isa.ops)
    assert [r.name for r in isa.used_reg_files()] == ["x"]


def test_every_declared_op_is_actually_used_by_the_table():
    # The container allows declaring more than the mops use; for a real ISA
    # an unused op means a missing instruction, so pin the stronger property.
    isa = rv32i()
    assert set(isa.ops) == isa.used_ops()


def test_memory_width_and_branch_condition_are_ops_not_sub_fields():
    # lb/lh/lw/lbu/lhu, sb/sh/sw and the six branches are distinct kinds, so
    # the µop record needs no size/sign field and no cond-kind field
    # (op.py header). auipc is likewise its own op, not an ADD.
    isa = rv32i()
    assert {o.name for o in O.LOADS}    == {"LB", "LH", "LW", "LBU", "LHU"}
    assert {o.name for o in O.STORES}   == {"SB", "SH", "SW"}
    assert {o.name for o in O.BRANCHES} == {"BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU"}
    for op in O.LOADS + O.STORES + O.BRANCHES + (O.AUIPC,):
        assert op in isa.used_ops(), op.name


def test_unit_routing_covers_every_op():
    isa = rv32i()
    for op in isa.ops:
        assert isa.units_for(op), f"no unit executes {op.name}"
    assert [u.name for u in isa.units_for(O.LW)] == ["mem"]
    assert [u.name for u in isa.units_for(O.BEQ)] == ["control"]
    assert [u.name for u in isa.units_for(O.AUIPC)] == ["alu"]


def test_x0_is_declared_not_special_cased():
    # RISC-V's hardwired zero is just a const_regs entry: rename bypasses
    # reads and discards writes, no ISA-specific logic in the engine.
    x = x_file()
    assert x.is_const(0) and not x.is_const(1)
    assert x.const_regs == {0: 0}


def test_the_operand_rules_and_the_description_share_one_register_class():
    # IsaBase matches reg files by identity, and the operand rules are module
    # constants — so the class they target must BE the class the description
    # declares. Sharing reg.RegFile is what makes that true by construction.
    isa = rv32i()
    assert isa.reg_file("x") is RegFile
    assert all(operand.target in (RegFile, ImmTarget)
               for uop in _uops(isa) for operand in uop.srcs + uop.dests)
    # Accepted cost: two builds share the class. x_file() is the way out.
    assert rv32i().reg_file("x") is isa.reg_file("x")
    assert x_file() is not RegFile and x_file() == RegFile


def test_operand_rules_agree_with_the_field_match_table():
    # A register operand's FieldRef name is derived from the field match,
    # never spelled twice, and it carries where its bits live.
    for operand, field in ((OPR_RD, FM.RD), (OPR_RS1, FM.RS1), (OPR_RS2, FM.RS2)):
        assert operand.index.name == field.name and operand.matcher is field
        assert operand.target is RegFile


def test_immediate_operands_carry_a_matcher_and_no_index():
    # An index answers "which register of the class", which an immediate has
    # not got — the layer above enforces exactly that, so the matcher is the
    # whole rule: which bits of the word carry the value.
    for imm in OPR_IMMS:
        assert imm.target is ImmTarget and imm.index is None and imm.matcher
    assert [i.matcher.name for i in OPR_IMMS] == [
        "imm_i", "imm_s", "imm_b", "imm_u", "imm_j", "shamt"]
    with pytest.raises(ValueError):                 # an index on one is refused
        Operand(ImmTarget, FieldRef("imm"), matcher=FM.IMM_I)


def test_immediates_ride_in_srcs_for_now():
    # Uop has no `imm` field while the matcher design is in flight, so the
    # immediate occupies a source slot — which contract §2 says it should not
    # (uop.py header). RV32I still fits the §2 cap: store and branch are the
    # widest at rs1 + rs2 + imm.
    isa = rv32i()
    with_imm = [uop for uop in _uops(isa)
                if any(o.target is ImmTarget for o in uop.srcs)]
    assert len(with_imm) == 27                  # every instruction but the R-type
    assert max(len(uop.srcs) for uop in _uops(isa)) == 3
    sw, = _uops(isa, O.SW)
    assert [o.matcher.name for o in sw.srcs] == ["rs1", "rs2", "imm_s"]


def test_rv32i_needs_no_micro_temps():
    # No AGU µop, and nothing else produces an intra-instruction value, so
    # RV32I has no real µtemp. The only Intermediate in the table is
    # ImmTarget, which stands for "this value comes from the encoding" — the
    # two are indistinguishable by type today, which is why this test names
    # the instance rather than the class. The µtemp mechanism proper is
    # pinned by the x86 read-modify-write shape in test_uop.py.
    isa = rv32i()
    temps = [operand.target
             for uop in _uops(isa) for operand in uop.srcs + uop.dests
             if isinstance(operand.target, Intermediate)]
    assert temps and all(t is ImmTarget for t in temps)


def test_load_and_store_are_single_uops():
    # RV32I addressing is base+imm only: the address is not a value a second
    # µop consumes, so no AGU µop and no address µtemp.
    isa = rv32i()
    lw, = _uops(isa, O.LW)
    assert [o.matcher.name for o in lw.srcs] == ["rs1", "imm_i"]
    assert lw.dests[0].index.name == "rd"

    sw, = _uops(isa, O.SW)
    assert [o.matcher.name for o in sw.srcs] == ["rs1", "rs2", "imm_s"]
    assert sw.dests == ()


def test_every_rv32i_instruction_is_one_uop():
    # No cracking in this ISA: jal/jalr were the last two-µop shapes and the
    # jump µop now writes its own link register (rv32i.py header).
    isa = rv32i()
    assert all(len(seq.uops) == 1 for mop in isa.mops for seq in mop.uop_seq)

    j, = _uops(isa, O.JMP)
    assert j.dests[0].index.name == "rd"            # rd = pc + ilen, in the jump µop

    jr, = _uops(isa, O.JMP_INDIRECT)
    assert jr.srcs[0].index.name == "rs1" and jr.dests[0].index.name == "rd"


def test_pc_is_not_a_register_class():
    # The program counter is front-end / ROB state, not something the engine
    # renames through a PRF port (reg.py header). Consequence: the
    # pc-relative shapes are missing an input this layer cannot name.
    isa = rv32i()
    assert [r.name for r in isa.reg_files] == ["x"]
    with pytest.raises(ValueError):
        isa.reg_file("pc")
    auipc, = _uops(isa, O.AUIPC)
    beq,   = _uops(isa, O.BEQ)
    # auipc is rd = pc + imm, but only the imm is nameable — see GAPS.
    assert [o.matcher.name for o in auipc.srcs] == ["imm_u"]
    assert beq.dests == ()                          # target is the control FU's


def test_field_positions_are_32_bit_and_segmented():
    assert ILEN_BYTES == 4
    assert FM.OPCODE.match_idx == ((0, 7),)
    assert FM.FUNCT7.match_idx == ((25, 32),)        # bits 31..25, end exclusive
    # The scrambled immediates are why match_idx is a tuple of segments.
    assert len(FM.IMM_S.match_idx) == 2 and len(FM.IMM_B.match_idx) == 4
    for field in (FM.OPCODE, FM.RD, FM.FUNCT3, FM.RS1, FM.RS2, FM.FUNCT7,
                  FM.IMM_I, FM.IMM_S, FM.IMM_B, FM.IMM_U, FM.IMM_J, FM.SHAMT):
        assert isinstance(field, InstrFieldMatch)
        for start, end in field.match_idx:
            assert 0 <= start < end <= 32           # inside the instruction word


def test_the_package_is_description_data_only():
    # CLAUDE.md §3: an ISA package holds data, never hardware — nothing it
    # imports may come from kathryn or carolyne.uarch. Checked on the actual
    # import statements, so prose in the header blocks may name them.
    import ast, pathlib

    pkg = pathlib.Path(__file__).resolve().parents[1] / "carolyne" / "isa" / "riscv"
    for source in sorted(pkg.glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert "kathryn" not in name, f"{source.name}: {name}"
                assert "uarch" not in name, f"{source.name}: {name}"
