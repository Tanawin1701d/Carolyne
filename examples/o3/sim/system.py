# THE SYSTEM — everything the universal sim (examples/sim) needs to run C
# programs on an O3 machine, built HERE because all of it is machine model:
# the config, the emitted Verilog, the images laid out for it and the cocotb
# test that knows its probes.
#
# THE MACHINE AND THE PROGRAMS ARE BUILT APART, so one machine runs many:
#   build_o3_sim_machine   config + emit, ONCE per process (Kathryn emits once)
#   build_o3_sim_program   images + the run spec, once per program
#
# ONE recipe for every machine family: a family binds its own config builder
# (a CALLABLE, never an import path), its compile_tool target and its cocotb
# test module, and this module does the rest. The sim receives SimMachine /
# SimProgram records and reads none of these files: the run spec is the
# family's handoff to its own test (run_spec.py), forwarded as one environment
# variable per program.

from __future__ import annotations

import os
import pathlib
from typing import Callable, Dict, Sequence, Tuple

from kathryn import emit_verilog

from carolyne.uarch.o3.config import CPUO3_Config
from examples.compile_tool import build_program, target_named
from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from examples.o3.core.build import build_debug_model
from examples.o3.core.mem_size import machine_mem_of
from examples.o3.sim.run_spec import SPEC_ENV, SPEC_FILE, build_run_spec, write_run_spec
from examples.sim.system import SimMachine, SimProgram

GenConfigForSizes = Callable[..., Tuple[CPUO3_Config, Dict[str, int]]]

REPO         = pathlib.Path(__file__).resolve().parents[3]
MACHINE_ROOT = REPO / "generated" / "sim" / "machine"


def machine_label(target: str, lanes: int, imem_bytes: int, dmem_bytes: int) -> str:
    return f"{target}_l{lanes}_i{imem_bytes}_d{dmem_bytes}"


def build_o3_sim_machine(gen_config_for_sizes : GenConfigForSizes,
                         target               : str,
                         test_module          : str,
                         test_case            : str,
                         imem_bytes           : int = DEFAULT_IMEM_BYTES,
                         dmem_bytes           : int = DEFAULT_DMEM_BYTES,
                         lanes                : int = 2,
                         machine_dir          : str = "") -> SimMachine:
    """The machine, emitted: what one compiled simulator serves every program with.

    - `gen_config_for_sizes(imem_bytes, dmem_bytes, fe_lanes=lanes)` returns the
      config AND the knobs that rebuild it in the simulator process
    - ONE emit per process: Kathryn's emitted names come from a process-global
      counter, so a second emit would miss the build cache
    """
    config, knobs = gen_config_for_sizes(imem_bytes, dmem_bytes, fe_lanes=lanes)
    label         = machine_label(target, lanes, imem_bytes, dmem_bytes)
    machine_dir   = machine_dir or str(MACHINE_ROOT / label)
    rtl_dir       = os.path.join(machine_dir, "rtl")
    emit_machine(config, rtl_dir)
    return SimMachine(label        = label,
                      target       = target,
                      rtl_dir      = rtl_dir,
                      test_module  = test_module,
                      test_case    = test_case,
                      config_knobs = dict(knobs),
                      config       = config)


def build_o3_sim_program(machine      : SimMachine,
                         c_sources    : Sequence[str],
                         run_dir      : str,
                         name         : str,
                         opt          : str  = "-O2",
                         log_enabled  : bool = True,
                         log_window   : int  = 2_500,
                         log_chunk    : int  = 0,
                         log_rob_rows : int  = 4,
                         max_cycles   : int  = 20_000,
                         idle_limit   : int  = 2_000) -> SimProgram:
    """One program laid out for the machine: its images and its run spec in `run_dir`.

    - the machine's MachineMem lays the images out, so they fit the very
      hardware the machine was emitted from
    """
    if machine.config is None:
        raise ValueError("build_o3_sim_program: the machine carries no config (built in another process?)")
    program = build_program(c_sources,
                            machine_mem_of(machine.config),
                            target  = target_named(machine.target),
                            name    = name,
                            opt     = opt,
                            out_dir = os.path.join(run_dir, "program"))

    # A CPUO3_Config cannot be serialised, so the spec carries the knobs the
    # family's builder was called with.
    spec_path = os.path.join(run_dir, SPEC_FILE)
    write_run_spec(spec_path,
                   build_run_spec(machine.config, program, run_dir,
                                  name         = name,
                                  target       = machine.target,
                                  log_enabled  = log_enabled,
                                  log_window   = log_window,
                                  log_chunk    = log_chunk,
                                  log_rob_rows = log_rob_rows,
                                  max_cycles   = max_cycles,
                                  idle_limit   = idle_limit,
                                  knobs        = machine.config_knobs))
    return SimProgram(name      = name,
                      run_dir   = run_dir,
                      env       = {SPEC_ENV: spec_path},
                      c_sources = tuple(c_sources))


def emit_machine(config: CPUO3_Config, rtl_dir: str) -> None:
    """Build the machine and write its Verilog and its manifest.

    - always debug=True: the manifest grows, the Verilog does not, so the build
      cache holds ONE entry whichever mode a run uses
    """
    os.makedirs(rtl_dir, exist_ok=True)
    build_debug_model(config)
    emit_verilog(rtl_dir, "top")
