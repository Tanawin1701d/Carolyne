# THE SIMULATION ITSELF — the one cocotb body every O3 family runs: for every
# program of the batch, reset the machine, load the images, release the
# memories and run until the program stops. A family's cocotb_test.py is the
# `@cocotb.test()` entry that calls `run_o3_program` with its own config builder.
#
# It runs in the SIMULATOR's process, so it rebuilds the model ONCE: a probe's
# `convert` is the MODEL probe's own method, and the manifest beside the
# Verilog names the nets it resolves against. No emit here — the design is
# already compiled — and every program of a batch is on the same machine.
#
# The order per program is what makes it run at all:
#   1. hold mrst for a few edges (the machine's state comes up clean, whatever
#      the previous program left)
#   2. deposit both images, word by word (the memories power up undefined)
#   3. release mrst
#   4. only THEN release each memory's read lock — it is a synchronous reset,
#      so a 1 deposited under mrst would be cleared
#
# Two modes. With `--log` every column of the slot table is read each cycle;
# with `--no-log` ONLY the store port is, which is all the exit door and the
# console need, and the run goes at the simulator's own speed.

from __future__ import annotations

from typing import Callable, List

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from kathryn.sim.ksim import KSim

from carolyne.debug.log             import (ConsoleCapture, EventsWriter, MmioDoors,
                                            StopWatch, apply_console, read_commit_events,
                                            read_redirect_event, read_store_event)
from carolyne.debug.log.events      import COMMIT, MEM_WRITE, MMIO
from carolyne.debug.log.o3_cycle    import O3CycleLogger, O3SimHandles
from carolyne.debug.log.slot_writer import ChunkedWriter, WindowWriter
from carolyne.debug.sim             import read_value
from carolyne.uarch.o3.config       import CPUO3_Config
from examples.o3.core.build         import build_debug_model
from examples.o3.core.run_spec      import RunSpec, read_hex_words, read_run_specs
from examples.sim.result            import RESULT_FILE, RunResult, write_result

CLOCK_NS = 10


def start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLOCK_NS, unit="ns").start())


def deposit_images(k, spec: RunSpec) -> None:
    """Both memory images, one word at a time, before the read locks open."""
    for bank_idx, path in enumerate(spec.instr_hex):
        bank = k.instr_mem.banks[bank_idx]
        for index, word in enumerate(read_hex_words(path)):
            bank[index].value = word
    data = k.data_mem.banks[0]
    for index, word in enumerate(read_hex_words(spec.data_hex)):
        data[index].value = word


async def reset_and_release(dut, k, spec: RunSpec) -> None:
    """Reset, load, then the read locks — in that order, and it matters."""
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


def open_trace(spec: RunSpec, table):
    if spec.log_chunk:
        return ChunkedWriter(spec.path_in("trace"), table, rows_per_file=spec.log_chunk)
    return WindowWriter(spec.path_in("trace.sl"), table, window=spec.log_window)


async def run_one_program(dut, k, model, config: CPUO3_Config, spec: RunSpec, store) -> RunResult:
    """One program: reset, load, run until the exit door, the watchdog or the
    cycle limit; write its console, events and result into its run dir."""
    doors = MmioDoors(**spec.doors)

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
    dut._log.info(f"{spec.name}: stopped {reason} after {cycle} cycles, exit {watch.exit_code}")
    dut._log.info(f"{spec.name}: console " + repr(console.text))
    return result


async def run_o3_program(dut, build_config: Callable[..., CPUO3_Config]) -> None:
    """Every program of the batch (or the one spec), on the machine the specs describe.

    - `build_config(**spec.config_kwargs)` is the family's own builder: the
      knobs are the FINAL widths, so nothing is derived twice and the two
      processes cannot disagree about the machine
    - every spec of a batch must name the same knobs: one compiled machine
    """
    specs: List[RunSpec] = read_run_specs()
    for spec in specs[1:]:
        if spec.config_kwargs != specs[0].config_kwargs:
            raise RuntimeError(
                f"batch program '{spec.name}' was laid out for other knobs "
                f"({spec.config_kwargs}) than '{specs[0].name}' ({specs[0].config_kwargs}) — "
                f"one compiled machine runs one batch")

    config = build_config(**specs[0].config_kwargs)
    k      = KSim(dut)
    model  = build_debug_model(config)      # rebuilt HERE, once: a model cannot cross a process
    store  = model.data_mem.dbg_write_wires[0].convert(k.data_mem.dbg_write_wires[0])

    start_clock(dut)
    failed = []
    for spec in specs:
        result = await run_one_program(dut, k, model, config, spec, store)
        if not result.stopped_at_exit:
            failed.append(f"{spec.name}: stopped on {result.stop_reason} after {result.cycles} "
                          f"cycles; console so far {result.console!r}")
    assert not failed, "programs that did not reach their exit door:\n" + "\n".join(failed)
