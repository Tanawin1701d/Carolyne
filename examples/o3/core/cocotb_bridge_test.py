# THE BOARD IN SIMULATION — the one cocotb test that runs a program through the
# HostBridge exactly as the board does: the same HostDriver, over the simulated
# top's host_* ports instead of PYNQ's MMIO. No probes, no model rebuild, so it
# serves every machine family.
#
# It reads the bridge run spec $CAROLYNE_BRIDGE_RUN_SPEC names and writes the
# RunResult into $CAROLYNE_BRIDGE_OUT_DIR (default: the spec's own directory).
#
# The host's wait is bounded in CLOCK EDGES here: the spec's cycle_limit is
# also the hardware's CYCLE_LIMIT, so FINISHED comes within that many cycles
# and the poll count is derived from it.

from __future__ import annotations

import math
import os
import pathlib
import sys

import cocotb

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from examples.fpga.bridge import (OUT_DIR_ENV, SPEC_ENV, HostDriver, HostMap,                  # noqa: E402
                                  read_bridge_run_spec, read_hex_words)
from examples.fpga.bridge.bridge_port_cocotb import (CocotbResetLine, CocotbWordPort,          # noqa: E402
                                                     start_clock)
from examples.fpga.result import run_result_of_outcome                                        # noqa: E402
from examples.sim.result import RESULT_FILE, write_result                                     # noqa: E402

POLL_CYCLES  = 64
POLL_S       = 1e-3          # the driver's unit of waiting; a poll here is POLL_CYCLES edges
SPARE_POLLS  = 16            # after the cycle limit: the exit store, the last status read


def polls_for(cycle_limit: int, timeout_s: float) -> float:
    """The driver's timeout, as seconds of POLL_S polls covering the cycle limit."""
    if cycle_limit <= 0:
        return timeout_s
    return (math.ceil(cycle_limit / POLL_CYCLES) + SPARE_POLLS) * POLL_S


@cocotb.test()
async def run_program(dut):
    """Load, start and run one program through the bridge until it stops."""
    spec     = read_bridge_run_spec()
    host_map = HostMap.from_dict(spec.host_map)
    out_dir  = os.environ.get(OUT_DIR_ENV) or os.path.dirname(os.path.abspath(os.environ[SPEC_ENV]))

    start_clock(dut)
    driver  = HostDriver(CocotbWordPort(dut, POLL_CYCLES), CocotbResetLine(dut), host_map)
    outcome = await driver.run_program([read_hex_words(path) for path in spec.instr_hex],
                                       read_hex_words(spec.data_hex),
                                       cycle_limit = spec.cycle_limit,
                                       timeout_s   = polls_for(spec.cycle_limit, spec.timeout_s),
                                       poll_s      = POLL_S)

    result = run_result_of_outcome(outcome, out_dir)
    write_result(os.path.join(out_dir, RESULT_FILE), result)
    dut._log.info(f"stopped: {result.stop_reason} after {result.cycles} cycles, exit {result.exit_code}")
    dut._log.info("console: " + repr(result.console))
    assert result.stop_reason == "exit", (
        f"the program did not reach its exit door: stopped on {result.stop_reason} after "
        f"{result.cycles} cycles; console so far {result.console!r}")
