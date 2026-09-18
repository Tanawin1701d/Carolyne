# The command line over the universal sim. The SYSTEMS table is the ONE place
# a machine family is named — the sim's own modules (runner, system, report,
# oracle) read none of it, so a new machine adds a row here and nothing else.
#
#   python -m examples.sim run examples/compile_tool/programs/hello.c
#   python -m examples.sim run hello.c --no-log            # let it run
#   python -m examples.sim run hello.c --window 500 --sim icarus
#   python -m examples.sim run a.c b.c --chunk 2000 --expect none

from __future__ import annotations

import argparse
import os
import sys

from examples.compile_tool.cli import parse_size
from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from examples.o3.rv32im.system import build_system as build_rv32im
from examples.sim.options import SimOptions
from examples.sim.oracle import compare_console, read_expected_text
from examples.sim.report import EXIT_HARNESS, describe, exit_code_for
from examples.sim.runner import SIM_ROOT, run_system

SYSTEMS = {"rv32im": build_rv32im}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "sim",
        description = "Compile a C program, build the machine for it, and "
                      "simulate it until the program stops.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="build a system and simulate it")
    run.add_argument("c_sources", nargs="+", metavar="source.c")
    run.add_argument("--target", default="rv32im", choices=sorted(SYSTEMS))
    run.add_argument("--name", default="", help="names the output directory")
    run.add_argument("--opt", default="-O2")
    run.add_argument("--sim", default="verilator", choices=("verilator", "icarus"))
    run.add_argument("--imem", type=parse_size, default=DEFAULT_IMEM_BYTES)
    run.add_argument("--dmem", type=parse_size, default=DEFAULT_DMEM_BYTES)
    run.add_argument("--lanes", type=int, default=2)
    run.add_argument("--out", default="", help="output directory (default: generated/sim/run/<name>)")

    log = run.add_mutually_exclusive_group()
    log.add_argument("--log", dest="log", action="store_true", default=True,
                     help="write the cycle-by-cycle slot table (the default)")
    log.add_argument("--no-log", dest="log", action="store_false",
                     help="read only the store port, and let the simulator run")

    keep = run.add_mutually_exclusive_group()
    keep.add_argument("--window", type=int, default=2500,
                      help="keep the last N cycles of the log (the default)")
    keep.add_argument("--chunk", type=int, default=0,
                      help="keep every cycle, N rows per file")

    run.add_argument("--max-cycles", type=int, default=20_000)
    run.add_argument("--idle-limit", type=int, default=2_000,
                     help="stop after this many cycles with no progress")
    run.add_argument("--rob-rows", type=int, default=4,
                     help="how many reorder-buffer entries the log prints")
    run.add_argument("--waves", action="store_true")
    run.add_argument("--expect", default="host",
                     help="host (compile and run the same C natively), none, or a file")
    return parser


def name_of(args) -> str:
    return args.name or os.path.splitext(os.path.basename(args.c_sources[0]))[0]


def run_dir_of(args, name: str) -> str:
    return args.out or str(SIM_ROOT / "run" / name)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    name = name_of(args)

    # --- the machine side: built whole, BEFORE the sim sees anything ------------
    system = SYSTEMS[args.target](args.c_sources, run_dir_of(args, name),
                                  name         = name,
                                  imem_bytes   = args.imem,
                                  dmem_bytes   = args.dmem,
                                  lanes        = args.lanes,
                                  opt          = args.opt,
                                  log_enabled  = args.log,
                                  log_window   = args.window,
                                  log_chunk    = args.chunk,
                                  log_rob_rows = args.rob_rows,
                                  max_cycles   = args.max_cycles,
                                  idle_limit   = args.idle_limit)

    # --- the sim side: run it, judge it, report it ------------------------------
    options = SimOptions(sim=args.sim, waves=args.waves, expect=args.expect)
    result  = run_system(system, options)
    verdict = compare_console(read_expected_text(system.c_sources, options.expect),
                              result.console)
    print(describe(system, result, verdict))
    return exit_code_for(result, verdict)


def run() -> None:
    """Entry point that reports a broken run as a message, not a traceback."""
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        sys.exit(EXIT_HARNESS)
