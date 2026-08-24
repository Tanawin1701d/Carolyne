# build_dispatch — the bus from rename to the back end, one wire row per
# front-end lane, carrying a field group per atomic operand. The first test is
# the usage documentation; the rest pin which kinds each group gets.
#
# A field is probed through the arena, because reading `row.name` builds a
# deferred reference and does not answer whether the field is there.

import pytest
from kathryn import Module, _session, init, reset

from carolyne.isa import (AtomicOperand, ExecUnit, FieldRef, InstrFieldMatch,
                          Intermediate, IsaBase, Mop, Operand, OperandRole,
                          RegFile, TargetKind, Uop, UopSeq)
from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType
from carolyne.uarch.o3.dispatch_helper import (DEST_KINDS, SRC_KINDS,
                                               build_dispatch,
                                               dispatch_entry_shape,
                                               dispatch_operand_kinds)
from carolyne.uarch.o3.operand_field import named_atomic_operands, operand_fields
from carolyne.uarch.o3.rsv_helper import rsv_id_width

ISA = Rv32i()
X   = ISA.reg_file("x")

# operand_field.KIND_ORDER — the order a group's fields land in.
ALL_KINDS = ("active", "valid", "wb_required", "data", "pr_idx", "ar_idx")


def _cfg(**overrides):
    kwargs = dict(isa=ISA, fe_lanes=2, commit_lanes=2, phy_specs=((X, 64),),
                  rsv_specs=(RsvSpec(True, 4, ISA.exec_units, RsvType.RSV_BRANCH),),
                  rob_depth=32, sptag_len=4)
    kwargs.update(overrides)
    return CPUO3_Config(**kwargs)


def _build(cfg, name="dispatch"):
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.bus = build_dispatch(cfg, name=name)

    return Host()


def _has_field(bus, field: str, row: int = 0) -> bool:
    try:
        _session.arena().karray_element_hcp(bus.ident, [row], field)
    except Exception:
        return False
    return True


def _group(bus, atm_operand) -> list:
    """Which kinds of that operand's group actually got built."""
    return [kind for kind in ALL_KINDS
            if _has_field(bus, f"{kind}_{atm_operand.name}")]


def test_a_dispatch_row_is_one_group_per_operand():
    cfg  = _cfg()
    host = _build(cfg)
    by_name = {a.name: _group(host.bus, a) for a in named_atomic_operands(ISA, "dispatch")}

    # A source off a register class: it waits on a value, so it carries the
    # value and both indexes.
    assert by_name["src_1"] == ["active", "valid", "data", "pr_idx", "ar_idx"]
    assert by_name["src_2"] == ["active", "valid", "data", "pr_idx", "ar_idx"]
    # RV32I's immediate names no register class, so neither index is there.
    assert by_name["src_3"] == ["active", "valid", "data"]
    # A destination: where the result goes, and whether it must land first.
    assert by_name["dest_1"] == ["active", "wb_required", "pr_idx", "ar_idx"]


def test_a_lane_carries_the_machine_fields_beside_its_operands():
    # The fixed half: what every reader downstream needs whatever the µop is —
    # whether the lane holds one, what it is, where it goes, and where it came
    # from. rsv_id is what lets a station read every lane and take only its own.
    cfg  = _cfg()
    host = _build(cfg)

    for field in ("valid", "is_spec", "spec_tag", "uop_idx", "rob_des_idx",
                  "rsv_id", "is_branch", "is_store", "pc", "npc"):
        assert _has_field(host.bus, field), field


def test_the_machine_fields_are_sized_from_the_config():
    cfg = _cfg()
    _cls, fields = dispatch_entry_shape(cfg)

    assert fields["spec_tag"]    == cfg.sptag_len
    assert fields["uop_idx"]     == cfg.uop_idx_width      # which µop of the ISA
    assert fields["rob_des_idx"] == cfg.rob_idx_width      # which ROB entry
    assert fields["rsv_id"]      == rsv_id_width(cfg)      # which station
    assert fields["pc"] == fields["npc"] == cfg.pc_width


def test_a_source_never_promises_a_writeback():
    # wb_required is a DESTINATION's promise that the writeback lands before
    # the instruction retires. A source writes nothing, so it has none.
    cfg  = _cfg()
    host = _build(cfg)

    assert "wb_required" not in SRC_KINDS
    for slot in ("src_1", "src_2", "src_3"):
        assert not _has_field(host.bus, f"wb_required_{slot}"), slot
    assert _has_field(host.bus, "wb_required_dest_1")


def test_a_destination_waits_on_nothing_and_holds_no_value():
    # At dispatch a destination's value does not exist — the FU has not run —
    # and it is not waiting on anything, so neither valid nor data is there.
    cfg  = _cfg()
    host = _build(cfg)

    assert "valid" not in DEST_KINDS and "data" not in DEST_KINDS
    assert not _has_field(host.bus, "valid_dest_1")
    assert not _has_field(host.bus, "data_dest_1")


def test_an_operand_with_no_class_carries_neither_index():
    # pr_idx and ar_idx name a register OF A CLASS. operand_field refuses them
    # for a µtemp rather than sizing them zero, so the group simply drops them.
    cfg  = _cfg()
    host = _build(cfg)
    imm  = next(a for a in named_atomic_operands(ISA, "dispatch") if not a.has_arch)

    assert imm.name == "src_3"
    assert dispatch_operand_kinds(imm) == ("active", "valid", "data")
    assert not _has_field(host.bus, "pr_idx_src_3")
    assert not _has_field(host.bus, "ar_idx_src_3")


def test_the_widths_come_from_the_isa_and_the_machine():
    cfg = _cfg()
    _cls, fields = dispatch_entry_shape(cfg)

    assert fields["pr_idx_src_1"].width == cfg.phy_idx_width(X) == 6   # machine
    assert fields["ar_idx_src_1"].width == X.index_width == 5          # ISA
    assert fields["data_src_1"].width == X.width == 32
    assert fields["data_src_3"].width == 32          # the µtemp's own width
    for flag in ("valid_src_1", "active_src_1", "wb_required_dest_1"):
        assert fields[flag].width == 1


def test_the_bus_is_one_row_per_front_end_lane():
    cfg  = _cfg(fe_lanes=4)
    host = _build(cfg)

    for lane in range(4):
        assert _has_field(host.bus, "active_src_1", row=lane), lane
    assert not _has_field(host.bus, "active_src_1", row=4)


def test_a_utemp_destination_keeps_the_kinds_that_need_no_index():
    # x86's AGU writes a µtemp: it has no architectural register, so no index
    # either, but it is still a destination that must produce its value.
    addr = Intermediate(32, "addr")
    core = AtomicOperand(OperandRole.DEST_W_REQ, "addr_out", intermediate=addr)

    assert dispatch_operand_kinds(core) == ("active", "wb_required")


def test_an_unnamed_operand_cannot_name_its_fields():
    # The name is the stem of every field built for the core, so a core without
    # one cannot be turned into hardware at all.
    unnamed = AtomicOperand(OperandRole.SRC, reg_file=X)
    dest    = AtomicOperand(OperandRole.DEST, "dest_1", reg_file=X)
    src_opr = Operand(unnamed, TargetKind.ARCH, FieldRef("rs1"))
    dst_opr = Operand(dest,    TargetKind.ARCH, FieldRef("rd"))
    uop     = Uop("ADD", 0, srcs=(src_opr,), dests=(dst_opr,))
    unit    = ExecUnit("alu", (uop,), src_operands=(unnamed,),
                       dest_operands=(dest,))
    isa     = IsaBase(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                      reg_files=(X,), atomic_operands=(unnamed, dest),
                      operands=(src_opr, dst_opr), exec_units=(unit,),
                      uops=(uop,),
                      mops=(Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
                                uop_seq=(UopSeq(uops=(uop,)),)),))

    with pytest.raises(ValueError, match="has no name"):
        named_atomic_operands(isa, "dispatch")


def test_a_one_register_class_has_no_architectural_index_to_store():
    # x86 FLAGS: index_width is 0, so there is nothing to choose and a 0-bit
    # field is not a legal width. ar_idx drops, pr_idx stays.
    flags = RegFile("flags", 6, 1)
    core  = AtomicOperand(OperandRole.DEST_W_REQ, "flags_out", reg_file=flags)
    opr   = Operand(core, TargetKind.ARCH)
    uop   = Uop("ADD", 0, dests=(opr,))
    unit  = ExecUnit("alu", (uop,), dest_operands=(core,))
    isa   = IsaBase(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                    reg_files=(flags,), atomic_operands=(core,), operands=(opr,),
                    exec_units=(unit,), uops=(uop,),
                    mops=(Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
                              uop_seq=(UopSeq(uops=(uop,)),)),))
    cfg = CPUO3_Config(isa=isa, fe_lanes=1, commit_lanes=1,
                       phy_specs=((flags, 8),),
                       rsv_specs=(RsvSpec(True, 4, (unit,), RsvType.RSV_EXEC),),
                       rob_depth=8, sptag_len=4)

    fields = operand_fields(cfg, core, dispatch_operand_kinds(core), "dispatch")
    assert "ar_idx_flags_out" not in fields
    assert "pr_idx_flags_out" in fields
    assert "active_flags_out" in fields and "wb_required_flags_out" in fields
