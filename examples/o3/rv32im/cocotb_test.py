# THE SIMULATION ITSELF — one cocotb test that loads the images, releases the
# memories and runs the machine until the program stops.
#
# It runs in the SIMULATOR's process, so it rebuilds the model: a probe's
# `convert` is the MODEL probe's own method, and the manifest beside the
# Verilog names the nets it resolves against. No emit here — the design is
# already compiled.
#
# The order at reset is what makes a program run at all:
#   1. deposit both images, word by word (the memories power up undefined)
#   2. hold mrst for a few edges and release it
#   3. only THEN release each memory's read lock — it is a synchronous reset,
#      so a 1 deposited under mrst would be cleared
#
# Two modes. With `--log` every column of the slot table is read each cycle;
# with `--no-log` ONLY the store port is, which is all the exit door and the
# console need, and the run goes at the simulator's own speed.

from __future__ import annotations

import pathlib
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from kathryn.sim.ksim import KSim  # noqa: E402

from carolyne.debug.log             import (ConsoleCapture, EventsWriter, MmioDoors,      # noqa: E402
                                            StopWatch, apply_console, read_commit_events,
                                            read_redirect_event, read_store_event)
from carolyne.debug.log.events      import COMMIT, MEM_WRITE, MMIO                        # noqa: E402
from carolyne.debug.log.o3_cycle    import O3CycleLogger, O3SimHandles                    # noqa: E402
from carolyne.debug.log.slot_writer import ChunkedWriter, WindowWriter                    # noqa: E402
from carolyne.debug.sim             import read_value                                     # noqa: E402
from examples.o3.core.build         import build_debug_model                              # noqa: E402
from examples.o3.rv32im.config      import gen_o3_rv32im_config                           # noqa: E402
from examples.o3.rv32im.run_spec    import read_hex_words, read_run_spec                  # noqa: E402
from examples.sim.result            import RESULT_FILE, RunResult, write_result           # noqa: E402

CLOCK_NS = 10


def build_config(spec):
    """The same machine the driver emitted, rebuilt from the spec's own knobs.

    - the knobs are the FINAL widths, so nothing is derived twice and the two
      processes cannot disagree about the machine
    """
    return gen_o3_rv32im_config(**spec.config_kwargs)


def deposit_images(k, spec) -> None:
    """Both memory images, one word at a time, before the read locks open."""
    for bank_idx, path in enumerate(spec.instr_hex):
        bank = k.instr_mem.banks[bank_idx]
        for index, word in enumerate(read_hex_words(path)):
            bank[index].value = word
    data = k.data_mem.banks[0]
    for index, word in enumerate(read_hex_words(spec.data_hex)):
        data[index].value = word


async def reset_and_release(dut, k, spec) -> None:
    """Clock, reset, then the read locks — in that order, and it matters."""
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())
    dut.mrst.value = 1
    for _ in range(spec.reset_cycles):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    deposit_images(k, spec)                 # the write ports are never locked
    await Timer(1, unit="ns")
    dut.mrst.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    k.instr_mem.read_ready.value = 1        # synchronous reset: only now does a 1 stick
    k.data_mem .read_ready.value = 1
    await Timer(1, unit="ns")


def open_trace(spec, table):
    if spec.log_chunk:
        return ChunkedWriter(spec.path_in("trace"), table, rows_per_file=spec.log_chunk)
    return WindowWriter(spec.path_in("trace.sl"), table, window=spec.log_window)


@cocotb.test()
async def run_program(dut):
    """Run until the exit door, the watchdog or the cycle limit."""
    spec    = read_run_spec()
    config  = build_config(spec)
    k       = KSim(dut)
    model   = build_debug_model(config)      # rebuilt HERE: a model cannot cross a process
    doors   = MmioDoors(**spec.doors)
    store   = model.data_mem.dbg_write_wires[0].convert(k.data_mem.dbg_write_wires[0])

    logger, sink, handles = None, None, None
    if spec.log_enabled:
        handles = O3SimHandles(model, k)
        logger  = O3CycleLogger(handles, config, rob_rows=spec.log_rob_rows)
        sink    = open_trace(spec, logger.table)

    console    = ConsoleCapture()
    events_out = EventsWriter(spec.path_in("events.jsonl"))
    progress   = (MMIO, MEM_WRITE, COMMIT) if spec.log_enabled else (MMIO, MEM_WRITE)
    watch      = StopWatch(spec.max_cycles, spec.idle_limit, progress)

    await reset_and_release(dut, k, spec)

    cycle, reason, pc_was = 0, None, None
    while reason is None:
        cycle += 1
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")

        events      = []
        store_event = read_store_event(store, doors, cycle)
        if store_event is not None:
            events.append(store_event)
        if spec.log_enabled:
            events += read_commit_events(handles.rob_commit_ok, handles.rob_com_row, cycle)
            pc_now  = read_value(handles.fetch_pc)
            hop     = read_redirect_event(pc_now, pc_was, spec.pc_step, config.fe_lanes, cycle)
            pc_was  = pc_now
            if hop is not None:
                events.append(hop)
            sink.write(cycle, logger.record(cycle, events))

        apply_console(console, events)
        events_out.write(cycle, events)
        reason = watch.note(cycle, events)

    if sink is not None:
        sink.close()
    events_out.close()
    console.write(spec.path_in("console.txt"), cycle)
    result = RunResult(stop_reason = reason,
                       cycles      = cycle,
                       exit_code   = watch.exit_code,
                       console     = console.text,
                       files       = {"console": spec.path_in("console.txt"),
                                      "events" : spec.path_in("events.jsonl")})
    write_result(spec.path_in(RESULT_FILE), result)
    dut._log.info(f"stopped: {reason} after {cycle} cycles, exit {watch.exit_code}")
    dut._log.info("console: " + repr(console.text))
    assert reason == "exit", (
        f"the program did not reach its exit door: stopped on {reason} at cycle {cycle}; "
        f"console so far {console.text!r}")
