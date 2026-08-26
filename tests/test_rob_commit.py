# Rob — the reorder buffer and the commit that drains it. The first test is the
# usage documentation: build the register architecture, build the ROB on it,
# and drive dispatch, writeback, commit and squash from one flow.
#
# These elaborate real hardware (reset -> @init -> gen_flow -> build_flow),
# which is where a bad index or a double-driven port actually fails.

import pytest
from kathryn import (Module, PipCon, build_flow, flow, gen_flow, init, reset,
                     set_top, wire, zif)

from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType
from carolyne.uarch.o3.reg_arch_mng import RegArchMng
from carolyne.uarch.o3.rob import Rob
from carolyne.uarch.o3.rob_helper import build_rob_dispatch

ISA = Rv32i()
X   = ISA.reg_file("x")


def _cfg(**overrides):
    kwargs = dict(isa=ISA, fe_lanes=2, commit_lanes=2, phy_specs=((X, 64),),
                  rsv_specs=(RsvSpec(True, 8, ISA.exec_units, RsvType.RSV_BRANCH),),
                  rob_depth=8, sptag_len=4)
    kwargs.update(overrides)
    return CPUO3_Config(**kwargs)


def _drive(cfg, commit_ports=None):
    """Build a ROB on a real register architecture and drive every event."""
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.reg_arch_mng = RegArchMng(cfg, rename_ports=cfg.fe_lanes,
                                   commit_ports=commit_ports or cfg.commit_lanes)
            self.rob  = Rob(cfg, self.reg_arch_mng)
            self.disp = build_rob_dispatch(cfg, cfg.fe_lanes, "rob_disp")

            self.commit_arb = PipCon(name="commit_stage")
            self.mis_pred   = wire(1).mark_input("mis_pred")
            self.mis_idx    = wire(cfg.rob_depth.bit_length() - 1).mark_input("mis_idx")
            self.wb_en      = wire(1).mark_input("wb_en")
            self.wb_idx     = wire(cfg.rob_depth.bit_length() - 1).mark_input("wb_idx")

        @flow
        def run(self):
            self.rob.on_dispatch(self.disp)
            with zif(self.wb_en):
                self.rob.on_write_back(self.wb_idx)
            # The driver owns the arbiter, so IT says a squash stops commit.
            self.commit_arb.set_reset(self.mis_pred)
            self.rob.build_commit(self.commit_arb)
            with zif(self.mis_pred):
                self.rob.on_mis_pred(self.mis_idx)
            self.rob.on_update_meta()

    host = Host()
    set_top(host)
    gen_flow()
    build_flow()
    return host


def test_a_rob_is_two_pointers_and_a_count():
    cfg  = _cfg()
    host = _drive(cfg)
    rob  = host.rob

    assert rob.idx_width == 3 and rob.depth == 8       # 8 entries
    # The count needs one value MORE than the depth, so a full buffer is not an
    # empty one — which two pointers of the same width cannot tell apart.
    assert rob.cnt_width == 4
    assert rob.alloc_ptr is not None and rob.com_ptr is not None
    assert rob.used_entry_cnt is not None


def test_commit_is_as_wide_as_the_config_says():
    host = _drive(_cfg(commit_lanes=4, rob_depth=8))
    assert len(host.rob.commit_ok) == 4
    # One materialised row per lane, so the commit block reads slots rather
    # than folding the table once per field.
    assert host.rob.com_row is not None


def test_every_front_end_lane_allocates_and_the_group_goes_together():
    # A µop goes to ONE station, but every instruction goes to the ROB, so the
    # allocation run is as wide as the front end and asks only whether a lane
    # is carrying something. The group lands whole or not at all, so the
    # return is ONE room bit beside the per-lane indices.
    cfg  = _cfg(fe_lanes=3, commit_lanes=2)
    host = _drive(cfg)
    fits, free_idx = host.rob.free_slots(host.disp)
    assert fits is host.rob.dispatch_fits                   # one answer, shared
    assert len(free_idx) == 3


def test_a_group_wider_than_the_buffer_is_refused():
    # All-or-nothing means a bundle that cannot fit an EMPTY buffer could never
    # dispatch at all — a deadlock the config states, so it fails here.
    cfg = _cfg(fe_lanes=16, commit_lanes=2, rob_depth=8)
    reset()
    with pytest.raises(ValueError, match="could never dispatch"):
        Rob(cfg, RegArchMng(cfg, rename_ports=16, commit_ports=2))


def test_a_rob_needs_a_power_of_two_depth():
    # Both pointers step modulo the buffer; at a power-of-two depth the modulo
    # is the register width and no wrap compare is built.
    cfg = _cfg(rob_depth=12, commit_lanes=2)
    reset()
    with pytest.raises(ValueError, match="power of two"):
        Rob(cfg, RegArchMng(cfg, rename_ports=2, commit_ports=2))


def test_a_one_entry_rob_is_refused():
    cfg = _cfg(rob_depth=1, commit_lanes=1)
    reset()
    with pytest.raises(ValueError, match="0 bits wide"):
        Rob(cfg, RegArchMng(cfg, rename_ports=2, commit_ports=1))


def test_a_commit_lane_and_a_commit_port_are_one_number():
    # A lane retires an instruction and a port returns its physical register:
    # the same thing counted twice, so the two must AGREE, not merely fit.
    cfg = _cfg(commit_lanes=4, rob_depth=8)
    reset()
    with pytest.raises(ValueError, match="commit ports"):
        Rob(cfg, RegArchMng(cfg, rename_ports=2, commit_ports=2))   # too few
    reset()
    with pytest.raises(ValueError, match="commit ports"):
        Rob(cfg, RegArchMng(cfg, rename_ports=2, commit_ports=6))   # too many
    reset()
    Rob(cfg, RegArchMng(cfg, rename_ports=2, commit_ports=4))       # exactly


def test_a_rename_table_elaborates_when_the_widths_differ():
    # Regression: Rt's stage chain is one row per RENAME PORT, and it used to
    # walk sptag_len of them — which indexes past the array whenever the two
    # differ, as they do here (2 rename ports, 4 tag bits).
    cfg = _cfg(fe_lanes=2, sptag_len=4)
    assert cfg.fe_lanes != cfg.sptag_len
    _drive(cfg)                                  # elaborating IS the assertion
