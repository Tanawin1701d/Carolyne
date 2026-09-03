# build_fetch_table — the fetch stage's record, one row per front-end lane,
# sized from the config the way decode's and the ROB's tables are. The first
# test is the usage documentation; the rest pin what the shape depends on.
#
# A field is probed through the arena, because reading `table[0].name` builds a
# deferred reference and does not answer whether the field is there.

import pytest
from kathryn import HwComponentType, Module, _session, init, reset

from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType
from carolyne.uarch.o3.fetch_helper import (FetchEntryBase, build_fetch_table,
                                            fetch_entry_shape)

ISA = Rv32i()
X   = ISA.reg_file("x")


def _cfg(**overrides):
    kwargs = dict(isa=ISA, fe_lanes=2, commit_lanes=2, phy_specs=((X, 64),),
                  rsv_specs=(RsvSpec(True, 4, ISA.exec_units, RsvType.RSV_BRANCH),),
                  rob_depth=32, sptag_len=4, st_buf_depth=4)
    kwargs.update(overrides)
    return CPUO3_Config(**kwargs)


def _build(cfg, name="fetch"):
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.table = build_fetch_table(cfg, name)

    return Host()


def _has_field(table, field: str, row: int = 0) -> bool:
    try:
        _session.arena().karray_element_hcp(table.ident, [row], field)
    except Exception:
        return False
    return True


def test_a_fetch_entry_is_where_it_sits_and_what_was_read():
    cfg  = _cfg()
    host = _build(cfg)

    for field in ("pc", "instr"):
        assert _has_field(host.table, field), field


def test_the_table_is_one_row_per_front_end_lane():
    cfg  = _cfg(fe_lanes=4)
    host = _build(cfg)

    for lane in range(4):
        assert _has_field(host.table, "pc", row=lane), lane
    assert not _has_field(host.table, "pc", row=4)


def test_the_widths_come_from_the_isa_through_the_config():
    cfg = _cfg()
    _cls, fields = fetch_entry_shape(cfg)

    assert fields["pc"] == cfg.pc_width == ISA.pc_width == 32
    assert fields["instr"] == cfg.instr_width == ISA.ilen_bytes * 8 == 32


def test_neither_width_has_a_default():
    # A 32 that happens to suit RV32I is a silent wrong answer for a 64-bit
    # ISA, so the class declares both fields unsized and every instantiation
    # must state them.
    reset()

    class Host(Module):
        @init
        def decl(self):
            with pytest.raises(TypeError, match="no width"):
                FetchEntryBase(HwComponentType.REG, (1,), "unsized")

    Host()


def test_the_record_carries_no_valid_bit():
    # A lane's occupancy is the fetch stage's pip grant; a field beside it
    # would be a second answer to one question.
    cfg  = _cfg()
    host = _build(cfg)

    assert not _has_field(host.table, "valid")
