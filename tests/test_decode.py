# build_decode_table — the decode stage's record, one row per front-end lane,
# sized from the ISA description the way the ROB's and a station's tables are.
# The first test is the usage documentation; the rest pin what the shape
# depends on.
#
# A field is probed through the arena, because reading `table[0].name` builds a
# deferred reference and does not answer whether the field is there.

import pytest
from kathryn import Module, _session, init, reset

from carolyne.isa import (AtomicOperand, ExecUnit, FieldRef, InstrFieldMatch,
                          Intermediate, IsaBase, Mop, Op, Operand, OperandRole,
                          RegFile, TargetKind, Uop, UopSeq)
from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType
from carolyne.uarch.o3.decode_helper import (build_decode_table,
                                             decode_atm_operands,
                                             decode_entry_shape,
                                             decode_operand_fields)

ISA = Rv32i()
X   = ISA.reg_file("x")


def _cfg(**overrides):
    kwargs = dict(isa=ISA, fe_lanes=2, commit_lanes=2, phy_specs=((X, 64),),
                  rsv_specs=(RsvSpec(True, 4, ISA.exec_units, RsvType.RSV_BRANCH),),
                  rob_depth=32, sptag_len=4)
    kwargs.update(overrides)
    return CPUO3_Config(**kwargs)


def _build(cfg, name="decode"):
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.table = build_decode_table(cfg, name)

    return Host()


def _has_field(table, field: str, row: int = 0) -> bool:
    try:
        _session.arena().karray_element_hcp(table.ident, [row], field)
    except Exception:
        return False
    return True


def test_a_decode_entry_is_the_machine_shape_plus_every_isa_operand():
    cfg  = _cfg()
    host = _build(cfg)

    # The fixed half: is the lane carrying a µop, where it came from, where the
    # next instruction is, and which µop of the vocabulary this is.
    for field in ("valid", "pc", "npc", "uop_idx"):
        assert _has_field(host.table, field), field

    # The ISA half, core-wide: RV32I's three source slots and its one
    # destination, whatever unit ends up running the µop.
    for field in ("active_src_1", "valid_src_1", "ar_idx_src_1",
                  "active_src_2", "valid_src_2", "ar_idx_src_2", "data_src_2",
                  "active_src_3", "valid_src_3", "data_src_3",
                  "active_dest_1", "wb_required_dest_1", "ar_idx_dest_1"):
        assert _has_field(host.table, field), field


def test_the_table_is_one_row_per_front_end_lane():
    cfg  = _cfg(fe_lanes=4)
    host = _build(cfg)

    for lane in range(4):
        assert _has_field(host.table, "valid", row=lane), lane
    assert not _has_field(host.table, "valid", row=4)


def test_no_physical_index_exists_before_rename():
    # Decode reads ar_idx off the encoding; pr_idx is what rename ANSWERS, so
    # it cannot be in a record built before rename ran.
    cfg  = _cfg()
    host = _build(cfg)

    for field in ("pr_idx_src_1", "pr_idx_src_2", "pr_idx_dest_1"):
        assert not _has_field(host.table, field), field


def test_data_is_built_only_where_a_slot_may_carry_a_utemp():
    # An immediate reaches the record as a µtemp target (RV32I's ImmTarget), so
    # data is the slot's own value. rs1 is always a register and never carries
    # one, so it gets no data field.
    cfg = _cfg()
    by_name = {a.name: a for a in decode_atm_operands(ISA)}

    assert not by_name["src_1"].has_imm
    assert "data_src_1" not in decode_operand_fields(cfg, by_name["src_1"])
    assert "data_src_2" in decode_operand_fields(cfg, by_name["src_2"])
    assert "data_src_3" in decode_operand_fields(cfg, by_name["src_3"])


def test_a_utemp_only_slot_has_no_architectural_index():
    # ar_idx names a register OF A CLASS, which a µtemp has not got — asking
    # for one would raise, so the builder does not ask.
    cfg = _cfg()
    imm = next(a for a in decode_atm_operands(ISA) if not a.has_arch)

    assert imm.name == "src_3"
    assert "ar_idx_src_3" not in decode_operand_fields(cfg, imm)
    assert "data_src_3" in decode_operand_fields(cfg, imm)


def test_both_directions_reach_decode():
    # Unlike the ROB, which holds only what RETIRES, decode carries the whole
    # µop: it has not been routed to a station yet.
    found = [a.name for a in decode_atm_operands(ISA)]
    assert found == ["src_1", "src_2", "src_3", "dest_1"]   # srcs, then dests


def test_the_widths_come_from_the_isa_and_the_config():
    cfg = _cfg()
    _cls, fields = decode_entry_shape(cfg)

    assert fields["pc"] == fields["npc"] == cfg.pc_width == ISA.pc_width
    assert fields["uop_idx"] == cfg.uop_idx_width
    assert fields["ar_idx_src_1"].width == X.index_width == 5
    assert fields["data_src_3"].width == 32                 # the µtemp's width
    assert fields["active_src_1"].width == fields["valid_src_1"].width == 1
    assert fields["wb_required_dest_1"].width == 1


def test_a_one_register_class_has_no_architectural_index_to_store():
    # x86 FLAGS: index_width is 0, so there is nothing to choose and a 0-bit
    # field is not a legal width.
    flags = RegFile("flags", 6, 1)
    core  = AtomicOperand(OperandRole.DEST_W_REQ, "flags_out", reg_file=flags)
    opr   = Operand(core, TargetKind.ARCH)          # no index: one register
    op    = Op("ADD")
    unit  = ExecUnit("alu", {op}, dest_operands=(core,))
    uop   = Uop(op, dests=(opr,))
    isa   = IsaBase(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                    reg_files=(flags,), atomic_operands=(core,), operands=(opr,),
                    ops=(op,), exec_units=(unit,), uops=(uop,),
                    mops=(Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
                              uop_seq=(UopSeq(uops=(uop,)),)),))
    cfg = CPUO3_Config(isa=isa, fe_lanes=1, commit_lanes=1,
                       phy_specs=((flags, 8),),
                       rsv_specs=(RsvSpec(True, 4, (unit,), RsvType.RSV_EXEC),),
                       rob_depth=8, sptag_len=4)

    fields = decode_operand_fields(cfg, core)
    assert "ar_idx_flags_out" not in fields
    assert "active_flags_out" in fields and "wb_required_flags_out" in fields


def test_an_unnamed_operand_cannot_name_its_fields():
    # The name is the stem of every field built for the core, so a core without
    # one cannot be turned into hardware at all.
    unnamed = AtomicOperand(OperandRole.SRC, reg_file=X)
    dest    = AtomicOperand(OperandRole.DEST, "dest_1", reg_file=X)
    src_opr = Operand(unnamed, TargetKind.ARCH, FieldRef("rs1"))
    dst_opr = Operand(dest,    TargetKind.ARCH, FieldRef("rd"))
    op      = Op("ADD")
    unit    = ExecUnit("alu", {op}, src_operands=(unnamed,),
                       dest_operands=(dest,))
    uop     = Uop(op, srcs=(src_opr,), dests=(dst_opr,))
    isa     = IsaBase(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                      reg_files=(X,), atomic_operands=(unnamed, dest),
                      operands=(src_opr, dst_opr), ops=(op,), exec_units=(unit,),
                      uops=(uop,),
                      mops=(Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
                                uop_seq=(UopSeq(uops=(uop,)),)),))

    with pytest.raises(ValueError, match="has no name"):
        decode_atm_operands(isa)
