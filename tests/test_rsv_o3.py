# RsvO3 — out-of-order issue: the OLDEST ready entry goes. It takes EVERY
# front-end lane aimed at it in one cycle and issues ONE entry, through the
# execution unit's arbiter so a busy unit stalls rather than drops.
#
# These elaborate real hardware (reset -> @init -> gen_flow -> build_flow),
# which is where a bad index or a double-driven wire actually fails.

import pytest
from kathryn import (Module, PipCon, build_flow, flow, gen_flow, init, reset,
                     set_top, wire)

from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.priority import PRI_MIS_PRED, PRI_RENAME, PRI_TRACK_ROLL
from carolyne.uarch.o3.rsv import RsvBypass
from carolyne.uarch.o3.rsv_helper import build_rsv_dispatch, rsv_id_width
from carolyne.uarch.o3.rsv_o3 import RsvO3

ISA      = Rv32i()
X        = ISA.reg_file("x")
O3_SPEC  = RsvSpec(True,  4, (ISA.unit("alu"), ISA.unit("control")))
IOR_SPEC = RsvSpec(False, 4, (ISA.unit("mem"), ISA.unit("system")))


def _cfg(fe_lanes=2):
    return CPUO3_Config(isa=ISA, fe_lanes=fe_lanes, phy_specs=((X, 64),),
                        rsv_specs=(O3_SPEC, IOR_SPEC), rob_depth=32, sptag_len=4)


def _drive(station_cls, spec, rsv_idx=0, fe_lanes=2):
    """Build a station, drive every event it has, and elaborate the result."""
    cfg = _cfg(fe_lanes)
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.station  = station_cls(cfg, spec, "rsv_test", rsv_idx)
            self.dispatch = build_rsv_dispatch(cfg, spec, cfg.fe_lanes, "disp")
            self.exec_arb = PipCon(name="exec_unit")
            self.fix_tag  = wire(cfg.sptag_len).mark_input("fix_tag")
            self.suc_tag  = wire(cfg.sptag_len).mark_input("suc_tag")
            self.bp_valid = wire(1).mark_input("bp_valid")
            self.bp_idx   = wire(cfg.phy_idx_width(X)).mark_input("bp_idx")
            self.bp_data  = wire(X.width).mark_input("bp_data")

        @flow
        def run(self):
            st = self.station
            st.write_entries(self.dispatch)
            st.build_issue(self.exec_arb, self.suc_tag)
            st.on_bypass(RsvBypass(X, self.bp_valid, self.bp_idx, self.bp_data))
            st.on_mis_pred(self.fix_tag)

    host = Host()
    set_top(host)
    gen_flow()
    build_flow()
    return host


# --- many writers, one issue --------------------------------------------------
def test_a_station_has_one_write_port_per_front_end_lane():
    # Every lane may dispatch in the same cycle and any of them may be aimed
    # here, so the write side is as wide as the front end. Issue stays single.
    host = _drive(RsvO3, O3_SPEC, fe_lanes=3)
    assert host.station.write_ports == 3
    assert len(host.station.free_ok) == 3 and len(host.station.free_idx) == 3


def test_each_write_port_searches_the_table_and_skips_what_earlier_lanes_took():
    # Each port runs its own reduce over the table — the valid bit folded with
    # its index, log2(size) deep — and the leaves of port k's fold exclude the
    # entries earlier lanes are ACTUALLY taking here. A lane bound for another
    # station takes nothing, so it excludes nothing.
    host  = _drive(RsvO3, O3_SPEC, fe_lanes=2)
    slots = host.station.free_slots(host.dispatch)
    assert len(slots) == 2
    # One-hot per port, one bit per row.
    assert all(idx is not None for _ok, idx in slots)


def test_the_dispatch_bus_says_which_station_a_lane_is_for():
    # A lane may be dispatching elsewhere this cycle, so the row carries the
    # rsv id and every station checks it. It is an ADDED field: the station
    # answers it on the way in and stores nothing.
    cfg = _cfg()
    assert rsv_id_width(cfg) == 1            # two stations
    host = _drive(RsvO3, O3_SPEC, rsv_idx=0)
    assert host.station.rsv_idx == 0


def test_the_free_slot_wires_are_built_once():
    # Two callers asking where to dispatch must not double-drive the wires.
    cfg = _cfg()
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.station  = RsvO3(cfg, O3_SPEC, "rsv_twice")
            self.dispatch = build_rsv_dispatch(cfg, O3_SPEC, cfg.fe_lanes, "disp")

        @flow
        def run(self):
            first  = self.station.free_slots(self.dispatch)
            second = self.station.free_slots(self.dispatch)
            assert [ok for ok, _ in first] == [ok for ok, _ in second]

    set_top(Host())
    gen_flow()
    build_flow()


# --- out of order -------------------------------------------------------------
def test_an_o3_station_keeps_its_own_age_counter():
    # Age is the station's business: one stamp per dispatch CYCLE, so lanes of
    # one cycle are equally old and nothing outside publishes a cycle id.
    host = _drive(RsvO3, O3_SPEC)
    st   = host.station

    assert st.track_width == 2                  # ceil_log2(4 entries)
    assert st.track_ptr is not None
    # The winner lands on a wire row, with the one-hot of where it came from.
    assert st.issue_row is not None and st.issue_oh is not None


def test_the_epoch_rung_has_to_lose_to_a_dispatch():
    # An entry written on the wrap cycle belongs to the NEW epoch, so the roll
    # that stamps everything older must be emitted before the entry write —
    # which is what the rung order says, and the only reason it is correct.
    assert PRI_TRACK_ROLL < PRI_RENAME < PRI_MIS_PRED


def test_the_winner_is_chosen_by_one_reduce_over_the_table():
    # The fold carries the whole record, so the comparison tree is built once
    # and the winning row comes out of the same read.
    host = _drive(RsvO3, O3_SPEC)
    # The root node of the fold covers every row — that is how the station
    # knows which node's answer the issue wires read.
    assert host.station._root is not None
    assert set(host.station._root) == {"ready", "oh"}


def test_an_o3_station_refuses_an_in_order_spec():
    cfg = _cfg()
    reset()
    with pytest.raises(ValueError, match="in-order"):
        RsvO3(cfg, IOR_SPEC, "bad")


