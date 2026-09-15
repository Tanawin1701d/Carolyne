# Every O3 module exposes its probes when the machine is built with debug=True:
# a PipStatusProbe per PipCon, a KarrayProbe per table, and the register-class
# blocks reached through the core. Nothing is exposed without the flag.

from __future__ import annotations

import json

from kathryn import build_model, emit_verilog, reset
from kathryn.sim.manifest.schema import SIM_MANIFEST_FILE

from carolyne.debug.sim import KarrayProbe, PipStatusProbe, RegClassProbe
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import rv32im_config


def build_debug_machine():
    reset()
    return build_model(build_machine(rv32im_config(fe_lanes=2, commit_lanes=2)), debug=True)


def test_every_stage_exposes_its_arbiter_and_its_table():
    core = build_debug_machine().core
    for stage, meta, table in ((core.fetch,    core.fetch.dbg_fetch_meta,       core.fetch.dbg_fetch),
                               (core.decode,   core.decode.dbg_decode_meta,     core.decode.dbg_decode),
                               (core.dispatch, core.dispatch.dbg_dispatch_meta, core.dispatch.dbg_dispatch_bus),
                               (core.rob,      core.rob.dbg_commit_meta,        core.rob.dbg_table),
                               (core.store_buf, core.store_buf.dbg_retire_meta, core.store_buf.dbg_table)):
        assert isinstance(meta, PipStatusProbe) and hasattr(meta, "pip_wait"), stage
        assert isinstance(table, KarrayProbe), stage
    assert core.rob.dbg_table.head is core.rob.com_ptr and core.rob.dbg_table.count is core.rob.used_entry_cnt
    assert core.store_buf.dbg_table.head is core.store_buf.ret_ptr
    assert not hasattr(core.dbg_backend_meta, "pip_wait")          # no_pip_master: no pip, no wait register


def test_every_station_and_complex_exposes_its_issue_paths():
    core = build_debug_machine().core
    for lane in core.issue_lanes:
        rsv = lane.rsv
        assert len(rsv.dbg_issue_metas) == rsv.unit_cnt and all(hasattr(p, "pip_wait") for p in rsv.dbg_issue_metas)
        assert len(rsv.dbg_exec_src) == rsv.unit_cnt
        in_order = hasattr(rsv, "head_ptr")
        assert (rsv.dbg_table.head is rsv.head_ptr) if in_order else not hasattr(rsv.dbg_table, "head")
        for exu in lane.execs:
            assert len(exu.dbg_stage_metas) == exu.exec_unit.stage_cnt
            assert all(hasattr(p, "pip_wait") for p in exu.dbg_stage_metas)


def test_the_core_names_the_register_class_blocks_and_the_memories_their_ports():
    m = build_debug_machine()
    for name, blocks in m.core.dbg_reg_arch.items():
        assert isinstance(blocks, RegClassProbe) and isinstance(blocks.arf.dbg_storage, KarrayProbe), name
        if hasattr(blocks, "prf"):
            assert isinstance(blocks.prf.dbg_storage, KarrayProbe) and isinstance(blocks.rt.dbg_master_rt, KarrayProbe)
    assert len(m.instr_mem.dbg_read_ports) == 2 and len(m.data_mem.dbg_write_ports) == 1
    assert all(not hasattr(p, "pip_wait") for p in m.instr_mem.dbg_read_ports)    # the read lock masters them, not a pip


def test_without_the_flag_nothing_is_exposed():
    reset()
    m = build_model(build_machine(rv32im_config(fe_lanes=2, commit_lanes=2)))
    assert not hasattr(m.core.fetch, "dbg_fetch_meta") and not hasattr(m.core, "dbg_reg_arch")


def test_the_manifest_reaches_every_probe(tmp_path):
    build_debug_machine()
    emit_verilog(str(tmp_path), "top")
    root = json.loads((tmp_path / SIM_MANIFEST_FILE).read_text())["root"]["children"]
    core = root["core"]["children"]
    assert core["fetch"]["children"]["dbg_fetch_meta"]["kind"] == "probe"
    assert core["rob"]["children"]["dbg_table"]["children"]["table"]["kind"] == "karray"
    assert core["dbg_reg_arch"]["kind"] == "dict"
    rf = next(iter(core["dbg_reg_arch"]["entries"].values()))
    assert rf["kind"] == "probe" and rf["children"]["arf"]["kind"] == "module"
    assert rf["children"]["arf"]["children"]["dbg_storage"]["kind"] == "probe"
    station = core["issue_lanes"]["items"][0]["items"][0]["children"]
    assert station["dbg_issue_metas"]["kind"] == "list" and station["dbg_issue_metas"]["items"][0]["kind"] == "probe"
    assert root["instr_mem"]["children"]["dbg_read_ports"]["items"][0]["kind"] == "probe"
