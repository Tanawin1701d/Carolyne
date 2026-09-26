# The MIPS32 package as usage documentation for a per-ISA description: it
# declares its own register classes, µops, units and mop table, and passes
# the lot to IsaBase — which is what actually validates it. These tests pin
# the rules a hand-written ISA package can get wrong, not the MIPS spec.

import pytest

from carolyne.isa import InstrFieldMatch, IsaBase
from carolyne.isa.mips import (
    ATOMIC_OPERANDS, HI_FILE, ILEN_BYTES, LO_FILE, MOP_TABLE, OPR_IMMS, OPR_REGS, GPR_FILE, RESET_PC,
    Mips32, UOPS, X_LEN, IMM_TARGET, field_match as FM, uop as U, build_gpr_file, build_hi_file,
)
from carolyne.isa.mips.operand import (OPR_RA, OPR_RD, OPR_RS, OPR_RS_SRC2, OPR_RT,
                                       OPR_RT_DEST, OPR_RT_SRC1, OPR_HI_SRC, OPR_LO_DEST)


def _uops(isa, want=None):
    """Every µop of the table, optionally only one template of it."""
    return [uop
            for mop in isa.mops for seq in mop.uop_seq for uop in seq.uops
            if want is None or uop is want]


def _one(isa, want):
    found, = _uops(isa, want)
    return found


def test_mips32_builds_and_passes_the_container_checks():
    # Construction IS the test: IsaBase rejects an undeclared µop, an
    # undeclared reg file, a µop no unit executes, or a slot a unit lacks.
    isa = Mips32()
    assert isinstance(isa, IsaBase) and isa.name == "mips32"
    assert isa.reg_file("r").amount == 32 and isa.reg_file("r").is_const(0)
    assert [r.name for r in isa.reg_files] == ["r", "hi", "lo"]
    assert {r.name for r in isa.used_reg_files()} == {"r", "hi", "lo"}


def test_mips32_is_a_subclass_supplying_defaults_not_a_factory():
    isa = Mips32()
    assert issubclass(Mips32, IsaBase)
    assert Mips32(name="mips32-dbg").mops is isa.mops
    assert type(isa).__post_init__ is IsaBase.__post_init__     # stays DATA
    with pytest.raises(ValueError, match="does not declare in uops"):
        Mips32(uops=(U.UOP_ADD,))
    assert Mips32().operands is isa.operands and Mips32().uops is isa.uops


def test_hi_and_lo_are_one_register_classes_with_no_index():
    # The accumulator halves are the x86-FLAGS shape the contract promises:
    # one register, index width 0, and an operand on them names no index.
    for reg_file in (HI_FILE, LO_FILE):
        assert reg_file.amount == 1 and reg_file.index_width == 0
        assert reg_file.width == X_LEN and reg_file.renamed
    assert OPR_HI_SRC.index is None and OPR_LO_DEST.index is None
    assert not OPR_HI_SRC.is_decoded and not OPR_HI_SRC.is_const   # implicit, and not a hardwired value
    assert build_hi_file() is not HI_FILE and build_hi_file() == HI_FILE


def test_r0_is_declared_not_special_cased():
    r = build_gpr_file()
    assert r.is_const(0) and not r.is_const(1)
    assert r.const_regs == {0: 0}
    assert r is not GPR_FILE and r == GPR_FILE


def test_every_declared_uop_is_used_exactly_once_by_the_table():
    isa   = Mips32()
    table = _uops(isa)
    assert len(table) == len(UOPS) == 63
    for template in UOPS:
        assert sum(u is template for u in table) == 1, template.name
    for uop in table:
        assert any(uop is template for template in UOPS), uop.name


def test_uop_ids_are_one_contiguous_run_per_unit():
    # The ids are grouped by the unit that runs them, so an out-of-order
    # station sharing two units tests one range per unit, not one equality
    # per µop (ExecUnitBase.uop_idx_ranges).
    isa = Mips32()
    assert {u.name: u.uop_idx_ranges() for u in isa.exec_units} == {
        "alu": ((0, 33),), "mem": ((34, 41),), "control": ((42, 53),), "muldiv": ((54, 62),)}
    assert sorted(u.uop_idx for u in isa.uops) == list(range(63))


def test_unit_routing_covers_every_uop():
    isa = Mips32()
    for uop in isa.uops:
        assert isa.units_for(uop), f"no unit executes {uop.name}"
    assert [u.name for u in isa.units_for(U.UOP_LW)]   == ["mem"]
    assert [u.name for u in isa.units_for(U.UOP_BEQ)]  == ["control"]
    assert [u.name for u in isa.units_for(U.UOP_JR)]   == ["control"]
    assert [u.name for u in isa.units_for(U.UOP_MFHI)] == ["muldiv"]
    assert [u.name for u in isa.units_for(U.UOP_MUL)]  == ["muldiv"]
    assert [u.name for u in isa.units_for(U.UOP_LUI)]  == ["alu"]


def test_the_slot_table_reads_as_the_manual():
    # One SLOT reads several FIELDS: which field fills it is the operand
    # rule's statement, and a body reads the slot by core.
    isa = Mips32()
    def fields(uop): return [o.matcher.name if o.matcher else o.index for o in uop.srcs]
    assert fields(_one(isa, U.UOP_ADDU))  == ["rs", "rt"]
    assert fields(_one(isa, U.UOP_SLL))   == ["rt", "sa"]          # value rt, count sa
    assert fields(_one(isa, U.UOP_SLLV))  == ["rt", "rs"]          # value rt, count rs
    assert fields(_one(isa, U.UOP_MOVZ))  == ["rs", "rt", "rd"]    # the old rd is a source
    assert fields(_one(isa, U.UOP_SW))    == ["rs", "rt", "imm16"]
    assert fields(_one(isa, U.UOP_LW))    == ["rs", "imm16"]
    assert fields(_one(isa, U.UOP_INS))   == ["rs", "rt", "bitfield"]
    assert fields(_one(isa, U.UOP_EXT))   == ["rs", "bitfield"]
    assert fields(_one(isa, U.UOP_BEQ))   == ["rs", "rt", "imm16"]
    assert fields(_one(isa, U.UOP_J))     == ["instr_index"]
    assert _one(isa, U.UOP_INS).dests[0].index.name == "rt"       # rt is read and written
    assert _one(isa, U.UOP_JAL).dests[0].index == 31              # $31 implicit
    assert _one(isa, U.UOP_BGEZAL).dests[0] is OPR_RA
    assert _one(isa, U.UOP_JALR).dests[0] is OPR_RD
    assert _one(isa, U.UOP_MFHI).srcs[0] is OPR_HI_SRC
    assert [o.atomic.name for o in _one(isa, U.UOP_MULT).dests] == ["dest_hi", "dest_lo"]
    assert [o.atomic.name for o in _one(isa, U.UOP_DIV).dests]  == ["dest_hi", "dest_lo"]
    assert _one(isa, U.UOP_MUL).dests[0] is OPR_RD                # hi/lo untouched
    assert max(len(uop.srcs) for uop in _uops(isa)) == 3


def test_every_branch_and_jump_declares_its_delay_slot():
    # The feature the engine will read one day; today the build holds the
    # slot to a nop (compile_tool verify.py). Exactly the twelve control µops.
    isa = Mips32()
    slotted = {u.name for u in isa.uops if u.has_feature("delay_slot")}
    assert slotted == {u.name for u in U.CONTROL} and len(slotted) == 12
    assert slotted == {u.name for u in isa.uops if u.has_feature("is_branch")}
    assert {u.name for u in isa.uops if u.has_feature("is_store")} == {"SB", "SH", "SW"}


def test_the_operand_rules_and_the_description_share_the_register_classes():
    isa = Mips32()
    assert isa.reg_file("r") is GPR_FILE and isa.reg_file("hi") is HI_FILE and isa.reg_file("lo") is LO_FILE
    assert all(operand.target in (GPR_FILE, HI_FILE, LO_FILE, IMM_TARGET)
               for uop in _uops(isa) for operand in uop.srcs + uop.dests)
    assert isa.mops is MOP_TABLE and Mips32().mops is MOP_TABLE
    assert isa.atomic_operands is ATOMIC_OPERANDS
    assert set(map(id, isa.operands)) == set(map(id, OPR_REGS + OPR_IMMS))


def test_register_operand_rules_agree_with_the_field_match_table():
    for operand, field in ((OPR_RS, FM.RS), (OPR_RT, FM.RT), (OPR_RD, FM.RD),
                           (OPR_RT_SRC1, FM.RT), (OPR_RS_SRC2, FM.RS), (OPR_RT_DEST, FM.RT)):
        assert operand.index.name == field.name and operand.matcher is field
        assert operand.target is GPR_FILE
    assert OPR_RD.is_dest and OPR_RT_DEST.is_dest and OPR_RS.is_src and OPR_RT_SRC1.is_src


def test_immediate_operands_carry_a_matcher_and_no_index():
    for imm in OPR_IMMS:
        assert imm.target is IMM_TARGET and imm.index is None and imm.matcher
        assert imm.is_src
    # the zero-extended forms state no rule: one contiguous field is the default
    rules = {imm.matcher.name + ("" if imm.imm_extract else " (default)") for imm in OPR_IMMS}
    assert "sa (default)" in rules and "imm16 (default)" in rules
    assert "bitfield" in rules and "instr_index" in rules


def test_every_matcher_in_the_table_states_a_value():
    isa = Mips32()
    for mop in isa.mops:
        assert mop.matcher_field is FM.OPCODE and mop.matcher_value is not None
        for seq in mop.uop_seq:
            assert (seq.matcher_field is None) == (seq.matcher_value is None), seq.uops[0].name
    opcodes = [m.matcher_value.match_value for m in isa.mops]
    assert len(set(opcodes)) == len(opcodes) == 26
    # the families refine by a second field; the rest are one instruction each
    families = {m.matcher_value.match_value[0] for m in isa.mops if len(m.uop_seq) > 1}
    assert families == {0b000000, 0b000001, 0b011100, 0b011111}
    # srl/rotr and srlv/rotrv state the field that tells them apart
    special = {seq.uops[0].name: seq.matcher_field.name for seq in isa.mops[0].uop_seq}
    assert special["SRL"]  == special["ROTR"]  == "funct+rs"
    assert special["SRLV"] == special["ROTRV"] == "funct+sa"


def test_the_three_instruction_formats_tile_the_word():
    assert [f.name for f in FM.FORMATS] == ["r_type", "i_type", "j_type"]
    for fmt in FM.FORMATS:
        assert fmt.width == 32, fmt.name
        covered = [bit for start, end in fmt.match_idx for bit in range(start, end)]
        assert sorted(covered) == list(range(32)), fmt.name
    assert all(fmt.match_idx[-1] == (26, 32) for fmt in FM.FORMATS)   # opcode is the top field


def test_field_positions_are_32_bit_and_the_reset_vector_is_the_architectures():
    assert ILEN_BYTES == 4 and RESET_PC == 0xBFC00000
    assert FM.OPCODE.match_idx == ((26, 32),) and FM.FUNCT.match_idx == ((0, 6),)
    for field in (FM.OPCODE, FM.RS, FM.RT, FM.RD, FM.SA, FM.FUNCT, FM.IMM16, FM.INSTR_INDEX,
                  FM.FUNCT_RS, FM.FUNCT_SA, FM.BITFIELD):
        assert isinstance(field, InstrFieldMatch)
        for start, end in field.match_idx:
            assert 0 <= start < end <= 32
    isa = Mips32()
    assert (isa.pc_width, isa.pc_align, isa.ilen_bytes, isa.reset_pc) == (X_LEN, 4, 4, 0xBFC00000)
    with pytest.raises(ValueError):
        isa.reg_file("pc")


def test_the_package_is_description_data_only():
    # CLAUDE.md §3: description modules hold data and never import kathryn;
    # the semantics modules may; carolyne.uarch is off-limits for every module.
    import ast, pathlib

    SEMANTICS = {"exec_unit_alu.py", "exec_unit_br.py", "exec_unit_ls.py",
                 "exec_unit_muldiv.py"}

    pkg = pathlib.Path(__file__).resolve().parents[2] / "carolyne" / "isa" / "mips"
    for source in sorted(pkg.glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if source.name not in SEMANTICS:
                    assert "kathryn" not in name, f"{source.name}: {name}"
                assert "uarch" not in name, f"{source.name}: {name}"
