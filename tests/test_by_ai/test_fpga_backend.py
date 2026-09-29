# The FPGA backend layer without a tool: the registry, the board table, the
# template filler, the generated inputs of a Vivado build, the cache key and
# the summary reader. Vivado itself runs only through the CLI (`build`).

from __future__ import annotations

import json
import pathlib

import pytest
from kathryn.sim.rtl import open_rtl

from examples.fpga.backend import BACKENDS, BitstreamRequest, bitstream_key, fill_text, get_backend
from examples.fpga.backend.vivado import VivadoBackend, parse_build_summary
from examples.fpga.backend.vivado.backend import FLOW_TCL, PARAMS_TCL, WRAPPER_MODULE, WRAPPER_V
from examples.fpga.bridge import HOST_BRAM_CELL, RESET_GPIO_CELL, HostMap

DOORS = {"putchar": 4092, "putint": 4093, "exit": 4094}
MAP   = HostMap(8192, 2, 16384, 4096, DOORS)


def fake_rtl_dir(tmp_path: pathlib.Path, text: str = "module MODULE_O3Machine0_0(input clk);\nendmodule\n") -> pathlib.Path:
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(text)
    (rtl / "sim_manifest.json").write_text(json.dumps({"backend": "verilog", "top_module": "MODULE_O3Machine0_0"}))
    return rtl


def a_request(rtl_dir, backend, clock_mhz=50, synth_only=False) -> BitstreamRequest:
    return BitstreamRequest(rtl_dir=str(rtl_dir), top_module="MODULE_O3Machine0_0", host_map=MAP,
                            board=backend.board("kv260"), clock_mhz=clock_mhz, synth_only=synth_only)


# ---- registry and boards -------------------------------------------------------------------

def test_the_registry_finds_a_backend_by_name_and_lists_on_a_miss():
    assert isinstance(get_backend("Vivado"), VivadoBackend)
    assert "vivado" in BACKENDS
    with pytest.raises(ValueError, match="no FPGA backend named 'quartus' — one of \\['vivado'\\]"):
        get_backend("quartus")


def test_the_kv260_row_states_the_part_and_the_board_files():
    board = VivadoBackend().board("kv260")
    assert board.part            == "xck26-sfvc784-2LV-c"
    assert board.board_part      == "xilinx.com:kv260_som:part0:1.4"
    assert "kv260_carrier" in board.board_connections
    assert board.host_base_addr  == 0xA0000000
    with pytest.raises(ValueError, match="knows no board 'zcu102'"):
        VivadoBackend().board("zcu102")


def test_a_missing_vivado_is_named_not_hidden(tmp_path):
    backend = VivadoBackend(vivado_bin=str(tmp_path / "no-vivado"))
    assert not backend.is_available()
    assert "not found" in backend.describe()
    with pytest.raises(RuntimeError, match="vivado not found"):
        backend.build(a_request(fake_rtl_dir(tmp_path), backend), tmp_path / "build")


# ---- templates --------------------------------------------------------------------------------

def test_fill_text_replaces_tokens_and_marker_lines_keeping_the_indent():
    text = "set part {PART}\n    # insert here\nset x {PART}{PART}\n"
    out  = fill_text(text, {"{PART}": "xc7"}, {"insert here": lambda indent: f"{indent}puts hi"})
    assert out == "set part xc7\n    puts hi\nset x xc7xc7\n"


def test_the_generated_inputs_carry_the_map_the_top_and_the_board(tmp_path):
    backend = VivadoBackend()
    build   = tmp_path / "build"
    backend.write_inputs(a_request(fake_rtl_dir(tmp_path), backend, clock_mhz=25), build)

    wrapper = (build / WRAPPER_V).read_text()
    assert f"module {WRAPPER_MODULE}" in wrapper
    assert "MODULE_O3Machine0_0 machine" in wrapper
    assert f"[{MAP.addr_bits}-1:0] bram_addr" in wrapper
    assert f"MEM_SIZE {MAP.window_bytes}" in wrapper

    params = (build / PARAMS_TCL).read_text()
    assert 'set part              "xck26-sfvc784-2LV-c"' in params
    assert "set clock_mhz         25" in params
    assert f"set window_bytes      {MAP.window_bytes}" in params
    assert f'"{HOST_BRAM_CELL}"' in params and f'"{RESET_GPIO_CELL}"' in params
    assert "{" not in params.replace("{PROJECT", "")     # every token was filled
    assert (build / FLOW_TCL).read_text().startswith("# build_bitstream.tcl")


def test_the_flow_script_names_the_cells_the_board_driver_looks_up():
    flow = (pathlib.Path(VivadoBackend().template_files()[0]).parent / FLOW_TCL).read_text()
    for needed in ("$host_bram_cell", "$reset_gpio_cell", "BRAM_PORTA", "C_DOUT_DEFAULT {0x00000001}",
                   "READ_LATENCY {1}", "build_summary.txt", "hw_handoff"):
        assert needed in flow, needed


# ---- the cache key --------------------------------------------------------------------------------

def test_the_key_follows_the_rtl_the_clock_and_the_stage_only(tmp_path):
    backend = VivadoBackend(vivado_bin=str(tmp_path / "no-vivado"))
    rtl     = open_rtl(fake_rtl_dir(tmp_path))
    base    = bitstream_key(rtl, backend, a_request(rtl.dir, backend))
    assert len(base) == 16
    assert bitstream_key(rtl, backend, a_request(rtl.dir, backend)) == base
    assert bitstream_key(rtl, backend, a_request(rtl.dir, backend, clock_mhz=25)) != base
    assert bitstream_key(rtl, backend, a_request(rtl.dir, backend, synth_only=True)) != base
    other = open_rtl(fake_rtl_dir(tmp_path / "other", "module MODULE_O3Machine0_0(input clk, input x);\nendmodule\n"))
    assert bitstream_key(other, backend, a_request(other.dir, backend)) != base


# ---- the summary ---------------------------------------------------------------------------------

def test_the_summary_reads_back_typed(tmp_path):
    path = tmp_path / "build_summary.txt"
    path.write_text("stage impl\ntiming_met 1\nwns_ns 3.217\nwhs_ns 0.05\nlut 41231\nlutram 5120\n"
                    "ff 13001\nbram 0.0\ndsp 9\nsynth_seconds 1830\nimpl_seconds 2400\n")
    facts = parse_build_summary(path)
    assert facts["timing_met"] is True and facts["wns_ns"] == 3.217
    assert facts["lut"] == 41231 and facts["bram"] == 0 and facts["stage"] == "impl"
