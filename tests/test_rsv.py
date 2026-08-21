# build_rsv_table — one reservation station's entry table, sized from the ISA
# description and the machine config. The first test is the usage
# documentation; the rest pin what the shape depends on.
#
# Building a Karray declares hardware, so every test opens an arena with
# reset() and builds inside a Module's @init — the same rule a real block obeys.
# A field is probed through the arena, because reading `table[0].name` builds a
# deferred reference and does not answer whether the field is there.

import pytest
from kathryn import Module, _session, init, reset

from carolyne.isa import (AtomicOperand, ExecUnit, FieldRef, InstrFieldMatch,
                          Intermediate, IsaBase, Mop, Op, Operand, OperandRole,
                          TargetKind, Uop, UopSeq)
from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.rsv_helper import (RsvIOREntry, RsvO3Entry, build_rsv_table,
                                   operand_fields, station_atm_operands)

ISA     = Rv32i()
X       = ISA.reg_file("x")
ALU     = ISA.unit("alu")
MEM     = ISA.unit("mem")           # the unit whose µops read the immediate
SYSTEM  = ISA.unit("system")        # ecall/ebreak: no operands at all


def _cfg(**overrides):
    kwargs = dict(isa=ISA, fe_lanes=2, commit_lanes=2, phy_specs=((X, 64),),
                  rsv_specs=(RsvSpec(True, 16, ISA.exec_units),),
                  rob_depth=32, sptag_len=8)
    kwargs.update(overrides)
    return CPUO3_Config(**kwargs)


def _build(cfg, spec, name=""):
    """Build one table in a fresh arena; hand back the module holding it."""
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.table = build_rsv_table(cfg, spec, name)

    return Host()


def _has_field(table, field: str) -> bool:
    try:
        _session.arena().karray_element_hcp(table.ident, [0], field)
    except Exception:
        return False
    return True


def test_a_station_table_is_the_isa_operands_plus_the_machine_shape():
    cfg  = _cfg()
    host = _build(cfg, RsvSpec(True, 16, (ALU,)))

    # The fixed half, sized from the config: which µop of the ISA this is
    # (uop_idx), the speculation tag, the PC — plus the age track, since this
    # station issues out of order.
    for field in ("valid", "is_spec", "spec_tag", "uop_idx", "pc",
                  "is_lower_track", "track"):
        assert _has_field(host.table, field), field

    # The ISA half: one field group per atomic operand the unit reads or
    # writes, named after it. RV32I's ALU reads src_1 and src_2 off register
    # class x and writes dest_1.
    for field in ("valid_src_1", "pr_idx_src_1", "data_src_1",
                  "valid_src_2", "pr_idx_src_2", "data_src_2",
                  "pr_idx_dest_1"):
        assert _has_field(host.table, field), field
    # A plain DEST always writes, so it carries no runtime bit.
    assert not _has_field(host.table, "required_dest_1")
    # src_3 is the immediate, which no ALU µop reads.
    assert not _has_field(host.table, "data_src_3")


def test_the_uop_id_is_sized_from_the_isa_not_the_rob():
    # uop_idx names one µop of the ISA's vocabulary, so one index means the
    # same µop anywhere in the core. RV32I declares 40 templates -> 6 bits,
    # which a 32-deep ROB's 5-bit index would have silently truncated.
    cfg = _cfg()
    assert cfg.uop_idx_width == 6 == (len(ISA.uops) - 1).bit_length()
    assert cfg.rob_idx_width == 5


def test_a_utemp_source_carries_only_its_data():
    # src_3 targets ImmTarget, an Intermediate: there is no PRF entry to wake
    # on, so the value rides with the µop and the entry holds data alone.
    cfg  = _cfg()
    spec = RsvSpec(True, 16, (MEM,))
    atm_operand = next(c for c in station_atm_operands(ISA, spec) if c.name == "src_3")
    assert not atm_operand.has_arch

    assert sorted(operand_fields(cfg, spec, atm_operand)) == ["data_src_3"]

    host = _build(cfg, spec)
    assert _has_field(host.table, "data_src_3")
    assert not _has_field(host.table, "pr_idx_src_3")
    assert not _has_field(host.table, "valid_src_3")


def test_only_a_write_required_dest_carries_the_required_bit():
    # A plain DEST always writes, so it needs no runtime bit; DEST_W_REQ is the
    # conditional one, and required_<name> is what makes it conditional.
    cfg  = _cfg()
    spec = RsvSpec(True, 16, (ALU,))

    plain = AtomicOperand(OperandRole.DEST,       "d_plain", reg_file=X)
    w_req = AtomicOperand(OperandRole.DEST_W_REQ, "d_req",   reg_file=X)
    assert plain.is_dest and w_req.is_dest              # both are destinations
    assert w_req.is_write_required and not plain.is_write_required

    assert sorted(operand_fields(cfg, spec, plain)) == ["pr_idx_d_plain"]
    assert sorted(operand_fields(cfg, spec, w_req)) == ["pr_idx_d_req",
                                                       "required_d_req"]


def test_the_index_and_data_widths_come_from_the_machine_and_the_class():
    # pr_idx is sized by the PHYSICAL file (64 entries -> 6 bits), data by the
    # ARCHITECTURAL class (32-bit registers).
    cfg  = _cfg()
    spec = RsvSpec(True, 16, (ALU,))
    atm_operand = next(c for c in station_atm_operands(ISA, spec) if c.name == "src_1")

    fields = operand_fields(cfg, spec, atm_operand)
    assert fields["pr_idx_src_1"].width == cfg.phy_idx_width(X) == 6
    assert fields["data_src_1"].width          == X.width == 32
    assert fields["valid_src_1"].width         == 1


def test_issue_order_picks_the_entry_class_and_the_track():
    cfg = _cfg()
    o3  = _build(cfg, RsvSpec(True,  16, (ALU,)), "rsv_o3")
    assert isinstance(o3.table, RsvO3Entry)
    assert _has_field(o3.table, "track")

    ior = _build(cfg, RsvSpec(False, 16, (ALU,)), "rsv_ior")
    assert isinstance(ior.table, RsvIOREntry)
    # In-order: position in the station is the order, so there is no age track.
    assert not _has_field(ior.table, "track")
    assert not _has_field(ior.table, "is_lower_track")


def test_an_out_of_order_station_needs_room_to_order():
    # track is ceil_log2(size), which is 0 bits at one entry.
    cfg = _cfg()
    with pytest.raises(ValueError, match="at least 2 entries"):
        _build(cfg, RsvSpec(True, 1, (ALU,)))
    _build(cfg, RsvSpec(False, 1, (ALU,)))      # in-order is fine at one


def test_atomic_operands_are_gathered_once_across_the_stations_units():
    # A station feeding several units collects each one once, srcs then dests.
    found = station_atm_operands(ISA, RsvSpec(True, 16, ISA.exec_units))
    assert [a.name for a in found] == ["src_1", "src_2", "src_3", "dest_1"]
    assert len({id(a) for a in found}) == len(found)


def test_a_station_whose_unit_reads_nothing_is_just_the_base_shape():
    # RV32I's system unit runs ecall/ebreak, which name no operand.
    cfg  = _cfg()
    spec = RsvSpec(True, 16, (SYSTEM,))
    assert station_atm_operands(ISA, spec) == ()

    host = _build(cfg, spec)
    assert _has_field(host.table, "uop_idx")
    assert not _has_field(host.table, "pr_idx_dest_1")


def test_an_unnamed_atomic_operand_cannot_name_its_fields():
    # The name is the stem of valid_/pr_idx_/data_, so one without a name has
    # no fields to build.
    unnamed = AtomicOperand(OperandRole.SRC, reg_file=X)
    dest    = AtomicOperand(OperandRole.DEST, "d", reg_file=X)
    src_opr = Operand(unnamed, TargetKind.ARCH, FieldRef("rs1"))
    dst_opr = Operand(dest,    TargetKind.ARCH, FieldRef("rd"))
    op      = Op("ADD")
    unit    = ExecUnit("alu", {op})
    uop     = Uop(op, srcs=(src_opr,), dests=(dst_opr,))
    isa     = IsaBase(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                      reg_files=(X,), atomic_operands=(unnamed, dest),
                      operands=(src_opr, dst_opr), ops=(op,), exec_units=(unit,),
                      uops=(uop,),
                      mops=(Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
                                uop_seq=(UopSeq(uops=(uop,)),)),))
    with pytest.raises(ValueError, match="no name"):
        station_atm_operands(isa, RsvSpec(True, 16, (unit,)))


def test_a_utemp_destination_has_no_index_to_hold():
    # x86's AGU writes a µtemp; the config sizes a physical file per register
    # CLASS, so there is no index width for one yet. Loud, not silent.
    cfg  = _cfg()
    spec = RsvSpec(True, 16, (ALU,))
    temp = AtomicOperand(OperandRole.DEST, "addr",
                         intermediate=Intermediate(32, "addr"))
    with pytest.raises(ValueError, match="µtemp"):
        operand_fields(cfg, spec, temp)
