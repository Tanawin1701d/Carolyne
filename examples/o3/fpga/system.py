# THE FPGA SYSTEM — the machine-side steps of the FPGA flow (examples/fpga),
# for ANY O3 family: the machine emitted WITH its HostBridge, and each program
# laid out for it. The flow receives the results and reads none of these files.
#
# The machine and the program are built APART: one bitstream runs every
# program, since the images are loaded at run time through the bridge. A
# family binds `build_o3_fpga_machine` to its own config builder and target
# (examples/o3/rv32im/fpga.py); the program side is family-blind.

from __future__ import annotations

import os
import pathlib
from typing import Callable, Dict, Sequence, Tuple

from kathryn import emit_verilog
from kathryn.sim.rtl import read_manifest

from carolyne.uarch.o3.config import CPUO3_Config
from examples.compile_tool import build_program, target_named
from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES, MemoryLayout
from examples.fpga.bridge import SPEC_FILE, BridgeRunSpec, HostMap, write_bridge_run_spec
from examples.fpga.bridge.bridge_hardware import HostBridge
from examples.fpga.system import FpgaMachine, FpgaProgram
from examples.o3.core.build import BridgeBuilder, build_debug_model
from examples.o3.core.mem_size import machine_mem_of

GenConfigForSizes = Callable[..., Tuple[CPUO3_Config, Dict[str, int]]]

REPO          = pathlib.Path(__file__).resolve().parents[3]
MACHINE_ROOT  = REPO / "generated" / "fpga" / "machine"
HOST_MAP_FILE = "host_map.json"

DEFAULT_CONSOLE_DEPTH = 8192        # cprime prints 6320 entries; every test program fits
DEFAULT_CYCLE_LIMIT   = 8_000_000
DEFAULT_TIMEOUT_S     = 60.0


def host_map_of(config: CPUO3_Config, console_depth: int) -> HostMap:
    """The HostBridge window for this machine, DERIVED from the same specs the
    hardware and the images are sized from.

    - the doors are the layout's MMIO words as data-memory WORD indices — what
      the store port reports, which is what the bridge compares against
    """
    machine_mem = machine_mem_of(config)
    layout      = MemoryLayout.from_spec(machine_mem)
    doors       = {name: layout.data_index(addr) for name, addr in layout.mmio_addrs.items()}
    return HostMap(imem_bytes    = machine_mem.imem_bytes,
                   imem_banks    = machine_mem.imem_banks,
                   dmem_bytes    = machine_mem.dmem_bytes,
                   console_depth = console_depth,
                   doors         = doors,
                   word_bytes    = machine_mem.word_bytes)


def machine_label(target: str, lanes: int, imem_bytes: int, dmem_bytes: int, console_depth: int) -> str:
    return f"{target}_l{lanes}_i{imem_bytes}_d{dmem_bytes}_c{console_depth}"


def build_o3_fpga_machine(gen_config_for_sizes : GenConfigForSizes,
                          target               : str,
                          imem_bytes           : int = DEFAULT_IMEM_BYTES,
                          dmem_bytes           : int = DEFAULT_DMEM_BYTES,
                          lanes                : int = 2,
                          console_depth        : int = DEFAULT_CONSOLE_DEPTH,
                          machine_dir          : str = "") -> FpgaMachine:
    """The machine with its bridge, emitted: what a bitstream is built from.

    - `gen_config_for_sizes(imem_bytes, dmem_bytes, fe_lanes=lanes)` returns the
      config AND the knobs that rebuild it (the sim's recipe, reused)
    """
    config, knobs = gen_config_for_sizes(imem_bytes, dmem_bytes, fe_lanes=lanes)
    label         = machine_label(target, lanes, imem_bytes, dmem_bytes, console_depth)
    machine_dir   = machine_dir or str(MACHINE_ROOT / label)
    rtl_dir       = os.path.join(machine_dir, "rtl")
    host_map      = host_map_of(config, console_depth)
    top_module    = emit_machine_with_bridge(config, host_map, rtl_dir)
    return FpgaMachine(label         = label,
                       target        = target,
                       rtl_dir       = rtl_dir,
                       top_module    = top_module,
                       host_map      = host_map,
                       host_map_path = os.path.join(rtl_dir, HOST_MAP_FILE),
                       config_knobs  = dict(knobs),
                       config        = config)


def build_o3_fpga_program(machine     : FpgaMachine,
                          c_sources   : Sequence[str],
                          run_dir     : str,
                          name        : str,
                          opt         : str   = "-O2",
                          cycle_limit : int   = DEFAULT_CYCLE_LIMIT,
                          timeout_s   : float = DEFAULT_TIMEOUT_S) -> FpgaProgram:
    """One program laid out for the machine, its images and run spec in `run_dir`."""
    if machine.config is None:
        raise ValueError("build_o3_fpga_program: the machine carries no config (built in another process?)")
    images  = os.path.join(run_dir, "program")
    program = build_program(c_sources,
                            machine_mem_of(machine.config),
                            target  = target_named(machine.target),
                            name    = name,
                            opt     = opt,
                            out_dir = images)
    instr_hex = tuple(os.path.join(images, f"{bank.name}.hex") for bank in program.image.instr_banks)
    data_hex  = os.path.join(images, f"{program.image.data_bank.name}.hex")
    spec_path = os.path.join(run_dir, SPEC_FILE)
    write_bridge_run_spec(spec_path, BridgeRunSpec(name        = name,
                                                   host_map    = machine.host_map.to_dict(),
                                                   instr_hex   = list(instr_hex),
                                                   data_hex    = data_hex,
                                                   cycle_limit = cycle_limit,
                                                   timeout_s   = timeout_s))
    return FpgaProgram(name      = name,
                       run_dir   = run_dir,
                       spec_path = spec_path,
                       c_sources = tuple(c_sources),
                       instr_hex = instr_hex,
                       data_hex  = data_hex)


def bridge_builder_for(host_map: HostMap) -> BridgeBuilder:
    """The `build_bridge` callable O3Machine takes: a HostBridge on this map."""
    def build_bridge(instr_mem, data_mem, store_port):
        return HostBridge(host_map, instr_mem, data_mem, store_port)
    return build_bridge


def emit_machine_with_bridge(config: CPUO3_Config, host_map: HostMap, rtl_dir: str) -> str:
    """Emit the machine with its HostBridge; write the map beside it; return the top module name.

    - debug=True like the sim's emit: the manifest grows, the Verilog does not
    """
    os.makedirs(rtl_dir, exist_ok=True)
    build_debug_model(config, bridge_builder_for(host_map))
    emit_verilog(rtl_dir, "top")
    host_map.write_json(os.path.join(rtl_dir, HOST_MAP_FILE))
    return read_manifest(rtl_dir)["top_module"]
