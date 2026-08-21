# build_rob_table — the reorder buffer's entry table, sized from the ISA
# description and the machine config, the way build_rsv_table sizes a
# station's. The first test is the usage documentation; the rest pin what the
# shape depends on.
#
# A field is probed through the arena, because reading `table[0].name` builds a
# deferred reference and does not answer whether the field is there.

import pytest
from kathryn import Module, _session, init, reset

from carolyne.isa import (AtomicOperand, ExecUnit, FieldRef, InstrFieldMatch,
                          Intermediate, IsaBase, Mop, Op, Operand, OperandRole,
                          RegFile, TargetKind, Uop, UopSeq)
from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.rob import (build_rob_table, rob_dest_operands,
                                   rob_entry_shape, rob_operand_fields)

ISA = Rv32i()
X   = ISA.reg_file("x")


def _cfg(**overrides):
    kwargs = dict(isa=ISA, fe_lanes=2, phy_specs=((X, 64),),
                  rsv_specs=(RsvSpec(True, 4, ISA.exec_units),),
                  rob_depth=32, sptag_len=4)
    kwargs.update(overrides)
    return CPUO3_Config(**kwargs)


def _build(cfg, name="rob"):
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.table = build_rob_table(cfg, name)

    return Host()


def _has_field(table, field: str) -> bool:
    try:
        _session.arena().karray_element_hcp(table.ident, [0], field)
    except Exception:
        return False
    return True


def test_a_rob_entry_is_the_machine_shape_plus_the_isa_destinations():
    cfg  = _cfg()
    host = _build(cfg)

    # The fixed half: has the writeback landed, what kind of instruction it is,
    # and where it came from. The PC follows the config, which reads it off the
    # ISA rather than holding a copy.
    for field in ("wb_fin", "is_branch", "is_store", "pc"):
        assert _has_field(host.table, field), field

    # The ISA half: one group per DESTINATION core. RV32I writes one register.
    for field in ("active_dest_1", "required_dest_1", "pr_idx_dest_1",
                  "ar_idx_dest_1"):
        assert _has_field(host.table, field), field


def test_only_destinations_reach_the_rob():
    # A source is the station's business; what RETIRES is a write.
    cfg  = _cfg()
    host = _build(cfg)

    assert [a.name for a in rob_dest_operands(ISA)] == ["dest_1"]
    for field in ("valid_src_1", "pr_idx_src_1", "data_src_1", "data_src_3"):
        assert not _has_field(host.table, field), field


def test_the_two_indexes_are_sized_from_different_things():
    # pr_idx addresses the PHYSICAL file the machine configured; ar_idx the
    # ARCHITECTURAL class the ISA declared, which is what commit writes into.
    cfg    = _cfg()
    fields = rob_operand_fields(cfg, rob_dest_operands(ISA)[0])

    assert fields["pr_idx_dest_1"].width == cfg.phy_idx_width(X) == 6
    assert fields["ar_idx_dest_1"].width == X.index_width == 5
    assert fields["active_dest_1"].width == fields["required_dest_1"].width == 1


def test_the_pc_follows_the_config():
    cfg = _cfg()
    _cls, fields = rob_entry_shape(cfg)
    assert fields["pc"] == cfg.pc_width == ISA.pc_width


def test_a_one_register_class_has_no_architectural_index_to_store():
    # x86 FLAGS: index_width is 0, so there is nothing to choose and the
    # elaborator wires the single register.
    flags = RegFile("flags", 6, 1)
    assert flags.index_width == 0

    core = AtomicOperand(OperandRole.DEST_W_REQ, "flags_out", reg_file=flags)
    opr  = Operand(core, TargetKind.ARCH)          # no index: one register
    op   = Op("ADD")
    unit = ExecUnit("alu", {op})
    uop  = Uop(op, dests=(opr,))
    isa  = IsaBase(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                   reg_files=(flags,), atomic_operands=(core,), operands=(opr,),
                   ops=(op,), exec_units=(unit,), uops=(uop,),
                   mops=(Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
                             uop_seq=(UopSeq(uops=(uop,)),)),))
    cfg  = CPUO3_Config(isa=isa, fe_lanes=1, phy_specs=((flags, 4),),
                        rsv_specs=(RsvSpec(True, 4, (unit,)),), rob_depth=8,
                        sptag_len=4)

    fields = rob_operand_fields(cfg, core)
    assert sorted(fields) == ["active_flags_out", "pr_idx_flags_out",
                              "required_flags_out"]

    host = _build(cfg, "rob_flags")
    assert _has_field(host.table, "pr_idx_flags_out")
    assert not _has_field(host.table, "ar_idx_flags_out")


def test_a_utemp_destination_has_nothing_to_retire():
    # A µtemp dies at the instruction boundary, so it never reaches commit.
    cfg  = _cfg()
    temp = AtomicOperand(OperandRole.DEST, "addr",
                         intermediate=Intermediate(32, "addr"))
    with pytest.raises(ValueError, match="µtemp"):
        rob_operand_fields(cfg, temp)


def test_an_unnamed_destination_cannot_name_its_fields():
    unnamed = AtomicOperand(OperandRole.DEST, reg_file=X)
    opr     = Operand(unnamed, TargetKind.ARCH, FieldRef("rd"))
    op      = Op("ADD")
    unit    = ExecUnit("alu", {op})
    uop     = Uop(op, dests=(opr,))
    isa     = IsaBase(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                      reg_files=(X,), atomic_operands=(unnamed,), operands=(opr,),
                      ops=(op,), exec_units=(unit,), uops=(uop,),
                      mops=(Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
                                uop_seq=(UopSeq(uops=(uop,)),)),))
    with pytest.raises(ValueError, match="no name"):
        rob_dest_operands(isa)
