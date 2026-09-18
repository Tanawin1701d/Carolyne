# The memory-port probe: what a memory exposes per port, what reaches the
# manifest, and the gate-first read a write access is.

from __future__ import annotations

import json

import pytest
from kathryn import SignalRef, build_model, emit_verilog, reset
from kathryn.sim.manifest.schema import SIM_MANIFEST_FILE

from carolyne.debug.sim import MemAccess, MemPortProbe, MemPortSimProbe
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config


def build_debug_machine():
    reset()
    return build_model(build_machine(gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)), debug=True)


# ---- what the memory exposes ---------------------------------------------------

def test_an_instruction_read_port_carries_its_bank_and_the_data_memory_does_not():
    m = build_debug_machine()
    assert len(m.instr_mem.dbg_read_wires) == 2                  # one port per fetch lane
    for probe in m.instr_mem.dbg_read_wires:
        assert isinstance(probe, MemPortProbe)
        assert isinstance(probe.bank, SignalRef)                 # two banks: the port names one
        assert isinstance(probe.valid, SignalRef)                # it reports a bank conflict
        assert not hasattr(probe, "enable")                      # a read has no write gate
    load = m.data_mem.dbg_read_wires[0]
    assert not hasattr(load, "bank")                             # one bank: no bank region at all


def test_the_store_port_carries_the_enable_that_says_a_write_happened():
    m = build_debug_machine()
    assert len(m.data_mem.dbg_write_wires) == 1
    store = m.data_mem.dbg_write_wires[0]
    assert isinstance(store.enable, SignalRef) and isinstance(store.data, SignalRef)
    assert store.index.global_id == m.data_mem.write_ports[0].addr_srcs[0].global_id


def test_the_rob_and_a_multi_stage_unit_expose_their_records():
    m = build_debug_machine()
    assert m.core.rob.dbg_com_row.table is m.core.rob.com_row
    mem_exu = m.core.issue_lanes[1].execs[0]                     # the load/store unit: two stages
    assert mem_exu.exec_unit.stage_cnt == 2 and len(mem_exu.dbg_stage_srcs) == 1
    alu_exu = m.core.issue_lanes[0].execs[0]                     # single stage: its record is the station's
    assert len(alu_exu.dbg_stage_srcs) == 0


def test_without_the_flag_no_port_wires_are_exposed():
    reset()
    m = build_model(build_machine(gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)))
    assert not hasattr(m.data_mem, "dbg_write_wires") and not hasattr(m.core.rob, "dbg_com_row")


def test_the_manifest_reaches_the_port_wires(tmp_path):
    build_debug_machine()
    emit_verilog(str(tmp_path), "top")
    root  = json.loads((tmp_path / SIM_MANIFEST_FILE).read_text())["root"]["children"]
    store = root["data_mem"]["children"]["dbg_write_wires"]
    assert store["kind"] == "list" and store["items"][0]["kind"] == "probe"
    fields = store["items"][0]["children"]
    assert {"index", "data", "enable"} <= set(fields) and "bank" not in fields
    assert fields["enable"]["kind"] == "signal"
    imem = root["instr_mem"]["children"]["dbg_read_wires"]["items"][0]["children"]
    assert "bank" in imem and "valid" in imem


# ---- the reader side, on fake sim nodes ----------------------------------------

class _CountingHandle:
    """A KSim handle that counts how many times its value was read."""
    def __init__(self, value: int) -> None:
        self.raw, self.reads = value, 0

    @property
    def value(self) -> int:
        self.reads += 1
        return self.raw


class _Node:
    def __init__(self, **children) -> None: self.__dict__.update(children)


def store_probe(enable: int, index: int = 7, data: int = 0x41):
    probe = MemPortProbe(index="i", data="d", enable="e")            # model side: the names it stores
    node  = _Node(index=_CountingHandle(index), data=_CountingHandle(data),
                  enable=_CountingHandle(enable))
    return probe.convert(node), node


def test_a_write_reports_where_it_landed_and_what_it_carried():
    sim, _node = store_probe(enable=1)
    assert isinstance(sim, MemPortSimProbe) and sim.is_write
    assert sim.write_access() == MemAccess(index=7, bank=None, data=0x41)


def test_no_write_reads_the_gate_and_nothing_else():
    sim, node = store_probe(enable=0)
    assert sim.write_access() is None
    assert node.enable.reads == 1 and node.index.reads == 0 and node.data.reads == 0


def test_a_read_port_refuses_write_access():
    sim = MemPortProbe(index="i", data="d", valid="v").convert(
        _Node(index=_CountingHandle(3), data=_CountingHandle(9), valid=_CountingHandle(1)))
    assert not sim.is_write and sim.read_valid() == 1 and sim.read_index() == 3
    with pytest.raises(ValueError, match="no enable"):
        sim.write_access()


def test_a_signal_the_model_did_not_store_reads_none():
    sim = MemPortProbe(index="i").convert(_Node(index=_CountingHandle(2)))
    assert sim.read_bank() is None and sim.read_data() is None and not sim.is_write
