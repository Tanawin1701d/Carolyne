# RsvIOR — in-order issue: the head goes and nothing overtakes it. Its lanes
# land in a run from the allocation pointer, and it issues ONE entry through
# the execution unit's arbiter so a busy unit stalls rather than drops.
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
from carolyne.uarch.o3.rsv_ior import RsvIOR

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


# --- in order -----------------------------------------------------------------
def test_an_in_order_station_is_two_pointers():
    # Position IS the age, so there is no track to compare — just where the
    # next entries land and which one issues next.
    host = _drive(RsvIOR, IOR_SPEC, rsv_idx=1)
    st   = host.station

    assert st.alloc_ptr is not None and st.head_ptr is not None
    assert st.idx_width == 2
    assert not hasattr(st, "track_ptr")


def test_in_order_lanes_land_in_a_run_and_leave_no_hole():
    # Port k takes alloc + k, and may only land if every earlier lane did: a
    # hole would be an entry issuing before one dispatched ahead of it.
    host  = _drive(RsvIOR, IOR_SPEC, rsv_idx=1)
    slots = host.station.free_slots(host.dispatch)
    assert len(slots) == host.station.write_ports


def test_an_in_order_station_refuses_an_out_of_order_spec():
    cfg = _cfg()
    reset()
    with pytest.raises(ValueError, match="out-of-order"):
        RsvIOR(cfg, O3_SPEC, "bad")


def test_an_in_order_station_needs_a_power_of_two():
    # Both pointers step modulo the table; at a power-of-two size the modulo is
    # the register width and no wrap compare is built.
    cfg = _cfg()
    reset()
    with pytest.raises(ValueError, match="power of two"):
        RsvIOR(cfg, RsvSpec(False, 6, (ISA.unit("mem"),)), "bad")


def test_more_write_ports_than_entries_is_refused():
    # The slot index is the offset MODULO the table, so on a 4-entry station
    # lane 0 and lane 4 would both land on alloc — two writes to one row at
    # equal priority, which is not statement order. The bound is <= size, not
    # < size: at exactly size the largest offset difference is size - 1, which
    # cannot be a whole table.
    cfg = _cfg(fe_lanes=6)
    reset()
    with pytest.raises(ValueError, match="write ports over"):
        RsvIOR(cfg, IOR_SPEC, "too_wide")

    # Four lanes over four entries is fine, and so is a narrower port count.
    reset()
    RsvIOR(_cfg(fe_lanes=4), IOR_SPEC, "exactly_full")
    reset()
    RsvIOR(_cfg(fe_lanes=6), IOR_SPEC, "narrowed", write_ports=4)


def test_a_one_entry_in_order_station_is_refused_at_construction():
    # Two pointers over one entry are 0 bits wide. Without the check this only
    # surfaced deep in Kathryn, as "dynamic index needs >= 1 bits, got 0".
    cfg = _cfg()
    reset()
    with pytest.raises(ValueError, match="0 bits wide"):
        RsvIOR(cfg, RsvSpec(False, 1, (ISA.unit("mem"),)), "bad")
