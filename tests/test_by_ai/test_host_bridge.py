# The HostBridge in the machine: it builds, its five ports reach the top with
# the map's widths, the emit carries the map beside it, and the Verilog parses.

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest
from kathryn import build_model, reset
from kathryn.signal import to_ref

from examples.fpga.bridge import HOST_ADDR, HOST_EN, HOST_PORT_NAMES, HOST_RDATA, HostMap
from examples.fpga.bridge.bridge_hardware import HostBridge
from examples.o3.core.build import build_machine
from examples.o3.core.fpga_system import HOST_MAP_FILE, bridge_builder_for, emit_machine_with_bridge
from examples.o3.core.mem_size import host_map_of
from examples.o3.mips32.config import gen_o3_mips32_config
from examples.o3.rv32im.config import gen_o3_rv32im_config

DEPTH = 16


def width_of(signal) -> int: return to_ref(signal)._slice.size


def test_host_map_of_derives_the_doors_and_sizes_from_the_config():
    config = gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2, instr_mem_idx_width=10,
                                  data_mem_idx_width=12)
    hm = host_map_of(config, DEPTH)
    assert (hm.imem_bytes, hm.imem_banks, hm.dmem_bytes) == (8192, 2, 16384)
    assert hm.doors == {"putchar": 4092, "putint": 4093, "exit": 4094}
    assert hm.console_depth == DEPTH


@pytest.mark.parametrize("gen_config", [gen_o3_rv32im_config, gen_o3_mips32_config])
def test_the_bridge_builds_inside_the_machine_and_reaches_the_top(gen_config):
    config = gen_config(fe_lanes=2, commit_lanes=2)
    hm     = host_map_of(config, DEPTH)
    reset()
    machine = build_model(build_machine(config, bridge_builder_for(hm)), debug=True)
    bridge  = machine.host_bridge
    assert isinstance(bridge, HostBridge)
    ports = {HOST_EN: bridge.host_en, "host_we": bridge.host_we, HOST_ADDR: bridge.host_addr,
             "host_wdata": bridge.host_wdata, HOST_RDATA: bridge.host_rdata}
    assert set(ports) == set(HOST_PORT_NAMES)
    assert all(port.is_io for port in ports.values())
    assert width_of(bridge.host_addr) == hm.addr_bits
    assert machine.instr_mem.host_write_refused is not None
    assert machine.data_mem.write_ports[0] is bridge.store_port     # it watches the core's store port


def test_a_machine_without_a_bridge_has_no_host_ports():
    config = gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)
    reset()
    machine = build_model(build_machine(config), debug=True)
    assert not hasattr(machine, "host_bridge")


def test_a_map_for_other_sizes_is_refused():
    config = gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)
    wrong  = HostMap(4096, 2, 16384, DEPTH, host_map_of(config, DEPTH).doors)
    reset()
    with pytest.raises(ValueError, match="host_map.imem_bytes"):
        build_machine(config, bridge_builder_for(wrong))


def test_the_emit_declares_the_ports_and_writes_the_map(tmp_path):
    config = gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)
    hm     = host_map_of(config, DEPTH)
    top    = emit_machine_with_bridge(config, hm, str(tmp_path))
    assert top.startswith("MODULE_O3Machine")
    assert HostMap.read_json(str(tmp_path / HOST_MAP_FILE)) == hm

    header = (tmp_path / "top.v").read_text()[:4000]
    assert re.search(rf"input\s+wire\s*(\[[^\]]*\])?\s*{HOST_EN}\b", header)
    assert re.search(rf"input\s+wire\s*\[{hm.addr_bits - 1}\s*:\s*0\]\s*{HOST_ADDR}\b", header)
    assert re.search(rf"output\s+(wire|reg)\s*\[31\s*:\s*0\]\s*{HOST_RDATA}\b", header)

    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not installed")
    files = sorted(str(p) for p in tmp_path.glob("*.v"))
    done  = subprocess.run(["iverilog", "-g2012", "-o", os.devnull, *files],
                           capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-3000:]
