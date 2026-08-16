# The RV32I package as usage documentation for a per-ISA description: it
# declares its own register classes, ops, units and mop table, and hands the
# lot to IsaBase — which is what actually validates it. These tests pin the
# invariants a hand-written ISA package can get wrong, not the RISC-V spec.

import pytest

from carolyne.isa import (
    AtomicOperand, FieldRef, Intermediate, InstrFieldMatch, IsaBase, Operand,
    OperandRole, TargetKind)
from carolyne.isa.riscv import (
    ILEN_BYTES, ImmTarget, MOP_TABLE, OPR_IMMS, OPR_RD, OPR_RS1, OPR_RS2,
    RegFile, Rv32i, UOPS, X_LEN, field_match as FM, op as O, uop as U, x_file,
)


def _uops(isa, op=None):
    """Every µop of the table, optionally only those naming one op."""
    return [uop
            for mop in isa.mops for seq in mop.uop_seq for uop in seq.uops
            if op is None or uop.op is op]


def test_rv32i_builds_and_passes_the_container_checks():
    # Construction IS the test: IsaBase rejects an undeclared op, an
    # undeclared reg file, or an op no unit executes.
    isa = Rv32i()
    assert isinstance(isa, IsaBase) and isa.name == "rv32i"
    assert isa.reg_file("x").amount == 32 and isa.reg_file("x").is_const(0)
    assert isa.used_ops() <= set(isa.ops)
    assert [r.name for r in isa.used_reg_files()] == ["x"]


def test_rv32i_is_a_subclass_supplying_defaults_not_a_factory():
    # A per-ISA package may subclass IsaBase (isa.py header), and RV32I does:
    # every vocabulary is a field DEFAULT, so Rv32i() is the whole description
    # and one part can be varied without a builder signature for the rest.
    isa = Rv32i()
    assert issubclass(Rv32i, IsaBase)
    dbg = Rv32i(name="rv32i-dbg")
    assert dbg.name == "rv32i-dbg" and dbg.mops is isa.mops

    # It stays DATA: no behaviour is overridden, so every inherited check runs.
    assert type(isa).__post_init__ is IsaBase.__post_init__
    with pytest.raises(ValueError):
        Rv32i(name="")
    with pytest.raises(ValueError, match="does not declare in uops"):
        Rv32i(uops=(U.UOP_ADD,))            # a mop reaches the other 39

    # Defaults are shared instances, which is what the identity checks need.
    assert Rv32i().operands is isa.operands and Rv32i().uops is isa.uops


def test_every_declared_op_is_actually_used_by_the_table():
    # The container allows declaring more than the mops use; for a real ISA
    # an unused op means a missing instruction, so pin the stronger property.
    isa = Rv32i()
    assert set(isa.ops) == isa.used_ops()


def test_memory_width_and_branch_condition_are_ops_not_sub_fields():
    # lb/lh/lw/lbu/lhu, sb/sh/sw and the six branches are distinct kinds, so
    # the µop record needs no size/sign field and no cond-kind field
    # (op.py header). auipc is likewise its own op, not an ADD.
    isa = Rv32i()
    assert {o.name for o in O.LOADS}    == {"LB", "LH", "LW", "LBU", "LHU"}
    assert {o.name for o in O.STORES}   == {"SB", "SH", "SW"}
    assert {o.name for o in O.BRANCHES} == {"BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU"}
    for op in O.LOADS + O.STORES + O.BRANCHES + (O.AUIPC,):
        assert op in isa.used_ops(), op.name


def test_unit_routing_covers_every_op():
    isa = Rv32i()
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
    isa = Rv32i()
    assert isa.reg_file("x") is RegFile
    assert all(operand.target in (RegFile, ImmTarget)
               for uop in _uops(isa) for operand in uop.srcs + uop.dests)
    # Accepted cost: two builds share the class. x_file() is the way out.
    assert Rv32i().reg_file("x") is isa.reg_file("x")
    assert x_file() is not RegFile and x_file() == RegFile
    # MOP_TABLE is shared on the same terms — frozen data all the way down, so
    # handing every build the same tuple changes nothing observable.
    assert isa.mops is MOP_TABLE and Rv32i().mops is MOP_TABLE


def test_operand_rules_agree_with_the_field_match_table():
    # A register operand's FieldRef name is derived from the field match,
    # never spelled twice, and it carries where its bits live.
    for operand, field in ((OPR_RD, FM.RD), (OPR_RS1, FM.RS1), (OPR_RS2, FM.RS2)):
        assert operand.index.name == field.name and operand.matcher is field
        assert operand.target is RegFile
    # Three different encoding fields, so no slot is ever both read and
    # written — which is what lets these stay shared constants (operand.py).
    assert OPR_RD.is_dest and OPR_RS1.is_src and OPR_RS2.is_src


def test_immediate_operands_carry_a_matcher_and_no_index():
    # An index answers "which register of the class", which an immediate has
    # not got — the layer above enforces exactly that, so the matcher is the
    # whole rule: which bits of the word carry the value.
    for imm in OPR_IMMS:
        assert imm.target is ImmTarget and imm.index is None and imm.matcher
        assert imm.is_src                           # a value flowing in, never written
    assert [i.matcher.name for i in OPR_IMMS] == [
        "imm_i", "imm_s", "imm_b", "imm_u", "imm_j", "shamt"]
    with pytest.raises(ValueError):                 # an index on one is refused
        Operand(AtomicOperand(OperandRole.SRC, intermediate=ImmTarget),
                TargetKind.TEMP, FieldRef("imm"), matcher=FM.IMM_I)


def test_immediates_ride_in_srcs_for_now():
    # Uop has no `imm` field while the matcher design is in flight, so the
    # immediate occupies a source slot — which contract §2 says it should not
    # (uop.py header). RV32I still fits the §2 cap: store and branch are the
    # widest at rs1 + rs2 + imm.
    isa = Rv32i()
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
    isa = Rv32i()
    temps = [operand.target
             for uop in _uops(isa) for operand in uop.srcs + uop.dests
             if isinstance(operand.target, Intermediate)]
    assert temps and all(t is ImmTarget for t in temps)


def test_load_and_store_are_single_uops():
    # RV32I addressing is base+imm only: the address is not a value a second
    # µop consumes, so no AGU µop and no address µtemp.
    isa = Rv32i()
    lw, = _uops(isa, O.LW)
    assert [o.matcher.name for o in lw.srcs] == ["rs1", "imm_i"]
    assert lw.dests[0].index.name == "rd"

    sw, = _uops(isa, O.SW)
    assert [o.matcher.name for o in sw.srcs] == ["rs1", "rs2", "imm_s"]
    assert sw.dests == ()


def test_every_rv32i_instruction_is_one_uop():
    # No cracking in this ISA: jal/jalr were the last two-µop shapes and the
    # jump µop now writes its own link register (rv32i.py header).
    isa = Rv32i()
    assert all(len(seq.uops) == 1 for mop in isa.mops for seq in mop.uop_seq)

    j, = _uops(isa, O.JMP)
    assert j.dests[0].index.name == "rd"            # rd = pc + ilen, in the jump µop

    jr, = _uops(isa, O.JMP_INDIRECT)
    assert jr.srcs[0].index.name == "rs1" and jr.dests[0].index.name == "rd"


def test_pc_is_not_a_register_class_but_still_has_a_width():
    # The program counter is front-end / ROB state, not something the engine
    # renames through a PRF port (reg.py header). Consequence: the
    # pc-relative shapes are missing an input this layer cannot name.
    isa = Rv32i()
    assert [r.name for r in isa.reg_files] == ["x"]
    with pytest.raises(ValueError):
        isa.reg_file("pc")
    # Not a class, but the engine still cannot size fetch or the redirect path
    # without these three — declared, and named from field_match.py.
    assert (isa.pc_width, isa.pc_align, isa.ilen_bytes) == (X_LEN, 4, 4)
    assert isa.pc_align_bits == 2                   # the two always-zero low bits
    auipc, = _uops(isa, O.AUIPC)
    beq,   = _uops(isa, O.BEQ)
    # auipc is rd = pc + imm, but only the imm is nameable — see GAPS.
    assert [o.matcher.name for o in auipc.srcs] == ["imm_u"]
    assert beq.dests == ()                          # target is the control FU's


def test_the_mop_table_wraps_every_uop_template_exactly_once():
    # uop.py is the instruction listing; the table is what binds it to
    # encodings. A template written but never wrapped in a UopSeq is an
    # instruction no decoder will ever see, and no container check catches it
    # — IsaBase validates what the table USES, not what the package declares.
    isa = Rv32i()
    table = _uops(isa)
    assert len(table) == len(UOPS) == 40

    # Identity, not equality — belt and braces. ecall and ebreak differ only
    # in their match value (both are TRAP on imm_i), so they were literally
    # equal templates until values landed; `is` did not depend on that.
    for template in UOPS:
        assert sum(u is template for u in table) == 1, template.op.name
    for uop in table:
        assert any(uop is template for template in UOPS), uop.op.name


def test_every_matcher_in_the_table_states_a_value():
    # The table is discriminable: wherever a rule names bits, it also says what
    # those bits must equal. Only LUI/AUIPC/JAL name no field at all — their
    # opcode alone identifies them, and that opcode is the Mop's rule.
    isa = Rv32i()
    for mop in isa.mops:
        assert mop.matcher_field is FM.OPCODE and mop.matcher_value is not None
        for seq in mop.uop_seq:
            for uop in seq.uops:
                if uop.matcher_field is None:
                    assert uop.matcher_value is None, uop.op.name
                else:
                    assert uop.matcher_value is not None, uop.op.name

    no_funct = [u.op.name for u in UOPS if u.matcher_field is None]
    assert no_funct == ["MOV_IMM", "AUIPC", "JMP"]          # lui, auipc, jal

    # Every opcode in the table is distinct — 11 groups, 11 patterns.
    opcodes = [m.matcher_value.match_value for m in isa.mops]
    assert len(set(opcodes)) == len(opcodes) == 11
    assert (0b0110011,) in opcodes and (0b1110011,) in opcodes

    # ecall vs ebreak: identical but for the imm value, which now separates them.
    ecall, ebreak = U.UOP_ECALL, U.UOP_EBREAK
    assert ecall.op is ebreak.op and ecall.matcher_field is ebreak.matcher_field
    assert ecall.matcher_value.match_value == (0b000000000000,)
    assert ebreak.matcher_value.match_value == (0b000000000001,)
    assert ecall != ebreak


def test_the_six_instruction_formats_tile_the_word():
    # A format is an InstrFieldMatch union of the fields it is built from, so
    # its segments must cover bits 0..31 exactly once — a field left out of a
    # format, or counted twice, surfaces right here.
    assert [f.name for f in FM.FORMATS] == [
        "r_type", "i_type", "s_type", "b_type", "u_type", "j_type"]
    for fmt in FM.FORMATS:
        assert fmt.width == 32, fmt.name
        covered = [bit for start, end in fmt.match_idx for bit in range(start, end)]
        assert sorted(covered) == list(range(32)), fmt.name

    # Fields are unioned in ascending first-bit order, so opcode leads every
    # format — but a field keeps its OWN segment order, which is why s_type's
    # third segment is imm_s's high half, above funct3 rather than after it.
    assert all(fmt.match_idx[0] == (0, 7) for fmt in FM.FORMATS)
    assert FM.S_TYPE.match_idx[:3] == ((0, 7), (7, 12), (25, 32))


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
