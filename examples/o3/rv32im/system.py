# THE SYSTEM — everything the universal sim (examples/sim) needs to run a C
# program on the O3 RV32IM machine, built HERE because all of it is machine
# model: the config, the images laid out for it, the emitted Verilog and the
# cocotb test that knows its probes.
#
# The sim receives the finished SimSystem and reads none of these files: the
# run spec is this package's handoff to its own test (run_spec.py), forwarded
# as one environment variable.

from __future__ import annotations

import os
from typing import Sequence

from kathryn import emit_verilog

from examples.compile_tool import build_program, target_named
from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from examples.o3.core.build import build_debug_model
from examples.o3.core.mem_size import machine_mem_of
from examples.o3.rv32im.config import gen_o3_rv32im_config_for_sizes
from examples.o3.rv32im.run_spec import SPEC_ENV, SPEC_FILE, build_run_spec, write_run_spec
from examples.sim.system import SimSystem

TEST_MODULE = "examples.o3.rv32im.cocotb_test"
TEST_CASE   = "run_program"


def build_system(c_sources    : Sequence[str],
                 run_dir      : str,
                 name         : str,
                 imem_bytes   : int  = DEFAULT_IMEM_BYTES,
                 dmem_bytes   : int  = DEFAULT_DMEM_BYTES,
                 lanes        : int  = 2,
                 opt          : str  = "-O2",
                 log_enabled  : bool = True,
                 log_window   : int  = 2_500,
                 log_chunk    : int  = 0,
                 log_rob_rows : int  = 4,
                 max_cycles   : int  = 20_000,
                 idle_limit   : int  = 2_000) -> SimSystem:
    """The machine-side steps — compile, emit, write the handoff — ready for the sim.

    - ONE config: its MachineMem lays the images out, emit_machine builds the
      very hardware those numbers came from
    """
    config, knobs = gen_o3_rv32im_config_for_sizes(imem_bytes, dmem_bytes, fe_lanes=lanes)
    rtl_dir       = os.path.join(run_dir, "rtl")

    program = build_program(c_sources,
                            machine_mem_of(config),
                            target  = target_named("rv32im"),
                            name    = name,
                            opt     = opt,
                            out_dir = os.path.join(run_dir, "program"))
    emit_machine(config, rtl_dir)

    # A CPUO3_Config cannot be serialised, so the spec names the factory that
    # rebuilds it and the knobs it was called with.
    spec_path = os.path.join(rtl_dir, SPEC_FILE)
    write_run_spec(spec_path,
                   build_run_spec(config, program, run_dir,
                                  name         = name,
                                  log_enabled  = log_enabled,
                                  log_window   = log_window,
                                  log_chunk    = log_chunk,
                                  log_rob_rows = log_rob_rows,
                                  max_cycles   = max_cycles,
                                  idle_limit   = idle_limit,
                                  knobs        = knobs))

    return SimSystem(name        = name,
                     run_dir     = run_dir,
                     rtl_dir     = rtl_dir,
                     test_module = TEST_MODULE,
                     test_case   = TEST_CASE,
                     env         = {SPEC_ENV: spec_path},
                     c_sources   = tuple(c_sources))


def emit_machine(config, rtl_dir: str) -> None:
    """Build the machine and write its Verilog and its manifest.

    - always debug=True: the manifest grows, the Verilog does not, so the build
      cache holds ONE entry whichever mode a run uses
    """
    os.makedirs(rtl_dir, exist_ok=True)
    build_debug_model(config)
    emit_verilog(rtl_dir, "top")
