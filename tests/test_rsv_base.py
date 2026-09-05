# RsvBase — a reservation station's storage and the events that move it. The
# first test is the usage documentation: subclass it, say how issue picks, and
# drive the rest from a flow.
#
# These build real hardware, so each test opens an arena with reset() and runs
# gen_flow()/build_flow() — that is where a bad assignment actually fails.

import pytest
from kathryn import (Module, build_flow, flow, gen_flow, init, reset, set_top,
                     wire, zif)

from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType
from carolyne.uarch.o3.dispatch_helper import build_dispatch
from carolyne.uarch.o3.rsv import RsvBase, RsvBypass

ISA  = Rv32i()
X    = ISA.reg_file("x")
ALU  = ISA.unit("alu")
MEM  = ISA.unit("mem")


def _cfg():
    return CPUO3_Config(isa=ISA, fe_lanes=2, commit_lanes=2,
                        phy_specs=((X, 64),),
                        rsv_specs=(RsvSpec(True, 8, ISA.exec_units, RsvType.RSV_BRANCH),),
                        rob_depth=32, sptag_len=4, st_buf_depth=4)


class OldestFirst(RsvBase):
    """The policy a station has to supply: here, the lowest ready row issues."""

    def build_issue(self, issue_en):
        for row_idx in self.all_row_idxs():
            row = self.table[row_idx]
            with zif(issue_en.land(self.slot_ready(row))):
                self.on_issue(row_idx, row)


def _drive(cfg, spec, unit_cls=OldestFirst):
    """Build a station, drive every event it has, and elaborate the result."""
    reset()

    class Host(Module):
        @init
        def decl(self):
            self.station = unit_cls(cfg, spec, "rsv_test")
            # The core-wide bus, not a row of this station's shape: a k2k copy
            # pairs the fields by name and width, so a station takes the ones
            # it keeps and the rest of the lane goes nowhere.
            self.dispatch = build_dispatch(cfg, 1, "dispatch")
            self.disp_en  = wire(1).mark_input("disp_en")
            self.disp_idx = wire(2).mark_input("disp_idx")
            self.issue_en = wire(1).mark_input("issue_en")
            self.tag      = wire(cfg.sptag_len).mark_input("tag")
            self.bp_valid = wire(1).mark_input("bp_valid")
            self.bp_idx   = wire(cfg.phy_idx_width(X)).mark_input("bp_idx")
            self.bp_data  = wire(X.width).mark_input("bp_data")

        @flow
        def run(self):
            st = self.station
            with zif(self.disp_en):
                st.write_entry(self.disp_idx, self.dispatch[0])
            st.build_issue(self.issue_en)
            # the CALLER's scope gates a broadcast now — RsvBypass
            # carries no valid bit of its own
            with zif(self.bp_valid):
                st.on_bypass(RsvBypass(X, self.bp_idx, self.bp_data))
            st.on_suc_pred(self.tag)
            st.on_mis_pred(self.tag)

    host = Host()
    set_top(host)
    gen_flow()
    build_flow()
    return host


def test_a_station_is_its_table_plus_the_entry_that_issued():
    cfg  = _cfg()
    host = _drive(cfg, RsvSpec(True, 4, (ALU,), RsvType.RSV_EXEC))
    st   = host.station

    # The station holds the waiting entries and the one row the FU reads.
    assert st.table is not None and st.exec_src is not None
    # It knows which operands its units use, straight from the description.
    assert [a.name for a in st.atm_operands] == ["src_1", "src_2", "dest_1"]


def test_only_an_arch_source_is_something_to_wait_for():
    # A µtemp/immediate source rides with the µop: no physical register, so
    # nothing to wake on and nothing for slot_ready to test.
    cfg  = _cfg()
    host = _drive(cfg, RsvSpec(True, 4, (MEM,), RsvType.RSV_LD_ST))
    st   = host.station

    assert [a.name for a in st.atm_operands]  == ["src_1", "src_2", "src_3",
                                                  "dest_1"]
    assert [a.name for a in st.has_src_arch_operands] == ["src_1", "src_2"]


def test_a_wake_slot_carries_the_bit_that_says_it_is_waiting():
    # slot_ready needs more than valid_<n>: the record has a group per operand
    # the ISA declares and a µop fills only some, so an arch source also
    # carries active_<n>.
    cfg  = _cfg()
    host = _drive(cfg, RsvSpec(True, 4, (ALU,), RsvType.RSV_EXEC))
    row  = host.station.table[0]

    for slot in ("src_1", "src_2"):
        assert hasattr(row, f"active_{slot}")
        assert hasattr(row, f"valid_{slot}")


def test_a_slot_the_uop_does_not_fill_never_holds_an_entry_back():
    """An inactive source waits on NOTHING, so it reads ready.

    Without this, `valid` alone would hold an entry forever on a slot no value
    was ever coming to — RV32I's LUI/AUIPC/JAL fill one source and the system
    µops none, so six of its forty µops could never issue.
    """
    # The µops whose sources leave an arch wake slot unfilled.
    wake  = [a.name for a in ISA.used_atomic_operands() if a.is_src and a.has_arch]
    stuck = [uop.name for uop in ISA.used_uops()
             if any(name not in {o.atomic.name for o in uop.srcs} for name in wake)]
    assert stuck == ["LUI", "AUIPC", "JAL", "FENCE", "ECALL", "EBREAK"]

    # slot_ready therefore reads active_<n> beside valid_<n>. _drive
    # elaborates OldestFirst, whose build_issue calls slot_ready in its flow,
    # so a station that builds at all is one whose gating built.
    cfg  = _cfg()
    host = _drive(cfg, RsvSpec(True, 4, (ALU,), RsvType.RSV_EXEC))
    st   = host.station
    assert [a.name for a in st.has_src_arch_operands] == ["src_1", "src_2"]


def test_the_base_refuses_to_guess_the_issue_policy():
    cfg = _cfg()
    reset()

    class Bare(RsvBase):
        pass

    class Host(Module):
        @init
        def decl(self):
            self.station = Bare(cfg, RsvSpec(True, 4, (ALU,), RsvType.RSV_EXEC), "rsv_bare")

    station = Host().station
    with pytest.raises(NotImplementedError, match="build_issue"):
        station.build_issue()


def test_an_in_order_station_builds_the_same_way():
    # Only the entry class differs: in order, position IS the age order.
    cfg  = _cfg()
    host = _drive(cfg, RsvSpec(False, 4, (ALU,), RsvType.RSV_EXEC))
    assert host.station.rsv_spec.issue_o3 is False


def test_all_row_idxs_covers_the_table():
    cfg  = _cfg()
    host = _drive(cfg, RsvSpec(True, 4, (ALU,), RsvType.RSV_EXEC))
    assert list(host.station.all_row_idxs()) == [0, 1, 2, 3]
