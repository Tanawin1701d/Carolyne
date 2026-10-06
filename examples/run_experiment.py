# THE EXPERIMENT: every test program on RV32IM and on MIPS32, in the simulator
# AND on the board, compared and saved. Each step is the Python call the CLIs
# make, written out in order so a reader can copy any one of them.
#
#   python -m examples.run_experiment                                # every program, both ISAs
#   python -m examples.run_experiment --programs hello.c fib.c
#   python -m examples.run_experiment --targets rv32im --clock-mhz 50
#
# Output, under generated/experiment/:
#   <target>/sim/<program>/      the sim run (images, result.json, console.txt)
#   <target>/fpga/<program>/     the board run (board/result.json, compare.json)
#   results.json                 every run, every verdict
#   results.txt                  the table printed at the end
#
# ONE EMIT PER PROCESS: Kathryn's emitted names come from a process-global
# counter, so each machine is emitted in a fresh process (`in_fresh_process`).
# Otherwise the second emit misses the simulator and bitstream caches.

from __future__ import annotations

import argparse
import json
import multiprocessing
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from typing import Callable, Dict, List, Sequence

from examples.fpga.compare import COMPARE_FILE, compare_runs, write_comparison
from examples.fpga.options import FpgaOptions
from examples.sim.oracle   import compare_console, compile_and_run_on_host
from examples.sim.result   import RunResult

REPO        = pathlib.Path(__file__).resolve().parents[1]
PROGRAMS    = REPO / "examples" / "compile_tool" / "programs"
OUT_ROOT    = REPO / "generated" / "experiment"
TARGET_ISAS = ("rv32im", "mips32")

IMEM_BYTES  = 8192
DMEM_BYTES  = 16384               # cprime needs 16K
LANES       = 2
OPT         = "-O2"
CYCLE_LIMIT = 8_000_000           # the sim's max_cycles and the bridge's cycle_limit
IDLE_LIMIT  = 2_000
TIMEOUT_S   = 60.0                # seconds the board waits per program


# ---- the simulator side (runs in its own process) ------------------------------------------

def run_sim_side(target: str, sources: Sequence[str]) -> Dict[str, RunResult]:
    """Every program on the target's sim machine, in one simulator process."""
    from examples.o3.mips32.sim import build_sim_machine as build_mips32_sim_machine
    from examples.o3.rv32im.sim import build_sim_machine as build_rv32im_sim_machine
    from examples.o3.sim.system import build_o3_sim_program
    from examples.sim.options   import SimOptions
    from examples.sim.runner    import run_batch
    from examples.sim.system    import SimBatch

    # 1. emit the machine with its debug probes: one compiled simulator serves every program
    build_sim_machine = {"rv32im": build_rv32im_sim_machine, "mips32": build_mips32_sim_machine}[target]
    machine           = build_sim_machine(imem_bytes=IMEM_BYTES, dmem_bytes=DMEM_BYTES, lanes=LANES)

    # 2. compile each program for that machine: images + the run spec in its own run dir
    programs = []
    for source in sources:
        name    = stem_of(source)
        run_dir = str(OUT_ROOT / target / "sim" / name)
        program = build_o3_sim_program(machine     = machine,
                                       c_sources   = [source],
                                       run_dir     = run_dir,
                                       name        = name,
                                       opt         = OPT,
                                       log_enabled = False,
                                       max_cycles  = CYCLE_LIMIT,
                                       idle_limit  = IDLE_LIMIT)
        programs.append(program)

    # 3. run the batch: compile (or reuse) the simulator, run every program back to back
    batch   = SimBatch(machine, tuple(programs))
    options = SimOptions(sim="verilator", expect="none")
    return run_batch(batch, options)


# ---- the FPGA side (runs in its own process) ------------------------------------------------

def run_fpga_side(target: str, sources: Sequence[str], options: FpgaOptions) -> Dict[str, RunResult]:
    """Every program on the target's bitstream, in one board session."""
    from examples.fpga.board import read_board_link
    from examples.fpga.runner import build_bitstream, describe_bitstream, run_many_on_board
    from examples.o3.fpga.system import build_o3_fpga_program
    from examples.o3.mips32.fpga import build_fpga_machine as build_mips32_fpga_machine
    from examples.o3.rv32im.fpga import build_fpga_machine as build_rv32im_fpga_machine

    # 1. emit the machine with its HostBridge
    build_fpga_machine = {"rv32im": build_rv32im_fpga_machine, "mips32": build_mips32_fpga_machine}[target]
    machine            = build_fpga_machine(imem_bytes=IMEM_BYTES, dmem_bytes=DMEM_BYTES, lanes=LANES)

    # 2. build the bitstream, or reuse the one cached for this rtl + board + clock
    bitstream = build_bitstream(machine, options)
    print(describe_bitstream(bitstream), flush=True)

    # 3. compile each program for that machine: images + bridge_run_spec.json
    programs = []
    for source in sources:
        name    = stem_of(source)
        run_dir = str(OUT_ROOT / target / "fpga" / name)
        program = build_o3_fpga_program(machine     = machine,
                                        c_sources   = [source],
                                        run_dir     = run_dir,
                                        name        = name,
                                        opt         = OPT,
                                        cycle_limit = CYCLE_LIMIT,
                                        timeout_s   = TIMEOUT_S)
        programs.append(program)

    # 4. upload once and run every program in one board session
    link = read_board_link(options.board_link)
    return run_many_on_board(machine, programs, bitstream, link, options)


# ---- the experiment --------------------------------------------------------------------------

def stem_of(source: str) -> str: return pathlib.Path(source).stem


def in_fresh_process(fn: Callable, *args):
    """`fn(*args)` in a new Python process, so its emit is the first one there."""
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as pool:
        return pool.submit(fn, *args).result()


def judge_target(target   : str,
                 sources  : Sequence[str],
                 expected : Dict[str, str],
                 sims     : Dict[str, RunResult],
                 boards   : Dict[str, RunResult],
                 ) -> List[dict]:
    """One row per program: each run against the host, and the sim against the board."""
    rows = []
    for source in sources:
        name  = stem_of(source)
        sim   = sims[name]
        board = boards[name]

        # host vs each run: stopped on the exit door, printed what the host printed
        sim_console_ok   = compare_console(expected[name], sim.console).ok
        board_console_ok = compare_console(expected[name], board.console).ok

        # sim vs board: stop, exit code, console and the EXACT cycle count
        comparison   = compare_runs(sim, board)
        compare_path = str(OUT_ROOT / target / "fpga" / name / COMPARE_FILE)
        write_comparison(compare_path, comparison)

        rows.append({"target"   : target,
                     "program"  : name,
                     "sim"      : asdict(sim),
                     "board"    : asdict(board),
                     "sim_ok"   : sim.stopped_at_exit   and sim_console_ok,
                     "board_ok" : board.stopped_at_exit and board_console_ok,
                     "same"     : comparison.ok})
    return rows


def row_passed(row: dict) -> bool: return row["sim_ok"] and row["board_ok"] and row["same"]


def ok_word(ok: bool) -> str: return "ok" if ok else "FAIL"


def render(rows: Sequence[dict]) -> str:
    lines = [f"{'target':<7} {'program':<12} {'sim cycles':>10} {'board cycles':>12} "
             f"{'sim':<5} {'board':<5} sim=board"]
    for row in rows:
        same = "same" if row["same"] else "DIFFERS"
        lines.append(f"{row['target']:<7} {row['program']:<12} "
                     f"{row['sim']['cycles']:>10} {row['board']['cycles']:>12} "
                     f"{ok_word(row['sim_ok']):<5} {ok_word(row['board_ok']):<5} {same}")
    passed = sum(row_passed(row) for row in rows)
    lines.append(f"{passed}/{len(rows)} passed")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_experiment",
                                     description="every program on RV32IM and MIPS32, sim and board, compared")
    parser.add_argument("--targets", nargs="*", default=list(TARGET_ISAS), choices=TARGET_ISAS)
    parser.add_argument("--programs", nargs="*", default=None,
                        help="program file names under programs/ (default: all)")
    parser.add_argument("--clock-mhz", type=int, default=50)
    parser.add_argument("--jobs", type=int, default=4, help="Vivado jobs: 4 keeps MIPS32 within 15 GB")
    parser.add_argument("--board-link", default=None, help="the board login file (default: board.local.json)")
    return parser


def main(argv=None) -> int:
    args    = build_parser().parse_args(argv)
    started = time.time()

    # 1. pick the programs and the flow options
    if args.programs:
        sources = sorted(str(PROGRAMS / name) for name in args.programs)
    else:
        sources = sorted(str(path) for path in PROGRAMS.glob("*.c"))
    options = FpgaOptions(clock_mhz  = args.clock_mhz,
                          jobs       = args.jobs,
                          board_link = args.board_link)

    # 2. the host oracle: what each program must print, once for both ISAs
    expected = {}
    for source in sources:
        expected[stem_of(source)] = compile_and_run_on_host([source])

    rows = []
    for target in args.targets:
        # 3. the simulator: one machine, one simulator process, every program
        print(f"=== {target}: simulator", flush=True)
        sims = in_fresh_process(run_sim_side, target, sources)

        # 4. the board: one bitstream, one board session, every program
        print(f"=== {target}: board", flush=True)
        boards = in_fresh_process(run_fpga_side, target, sources, options)

        # 5. judge each program: host vs sim, host vs board, sim vs board
        rows += judge_target(target, sources, expected, sims, boards)

    # 6. save every run and verdict, and the table
    table = render(rows)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (OUT_ROOT / "results.txt" ).write_text(table + "\n", encoding="utf-8")
    print()
    print(table)
    print(f"saved in {OUT_ROOT} after {time.time() - started:.0f}s")
    return 0 if all(row_passed(row) for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
