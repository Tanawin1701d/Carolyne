# The command line over the universal sim. The SYSTEMS table is the ONE place
# a machine family is named — the sim's own modules (runner, system, report,
# oracle) read none of it, so a new machine adds a row here and nothing else.
#
#   python -m examples.sim run   examples/compile_tool/programs/hello.c        # one program (several files = one program)
#   python -m examples.sim run   hello.c --no-log                              # let it run
#   python -m examples.sim batch hello.c fib.c hanoi.c --dmem 16384 --no-log   # one machine, one simulator, three programs
#   python -m examples.sim run   hello.c --window 500 --sim icarus
#
# `run` and `batch` build the machine ONCE and then one or many programs on
# it; a batch runs every program in one simulator process, so a program costs
# its own cycles and nothing else.

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

from examples.compile_tool.cli import parse_size
from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from examples.o3.sim.system import build_o3_sim_program
from examples.o3.mips32.sim import build_sim_machine as build_mips32_machine
from examples.o3.rv32im.sim import build_sim_machine as build_rv32im_machine
from examples.sim.options import SimOptions
from examples.sim.oracle import Verdict, compare_console, read_expected_text
from examples.sim.report import EXIT_HARNESS, EXIT_OK, describe, exit_code_for
from examples.sim.result import RunResult
from examples.sim.runner import SIM_ROOT, run_batch
from examples.sim.system import SimBatch, SimMachine, SimProgram

SYSTEMS = {"rv32im": build_rv32im_machine, "mips32": build_mips32_machine}


# ---- the parser -------------------------------------------------------------------------

def add_machine_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", default="rv32im", choices=sorted(SYSTEMS))
    parser.add_argument("--imem", type=parse_size, default=DEFAULT_IMEM_BYTES)
    parser.add_argument("--dmem", type=parse_size, default=DEFAULT_DMEM_BYTES)
    parser.add_argument("--lanes", type=int, default=2)


def add_program_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--opt", default="-O2")
    parser.add_argument("--sim", default="verilator", choices=("verilator", "icarus"))

    log = parser.add_mutually_exclusive_group()
    log.add_argument("--log", dest="log", action="store_true", default=True,
                     help="write the cycle-by-cycle slot table (the default)")
    log.add_argument("--no-log", dest="log", action="store_false",
                     help="read only the store port, and let the simulator run")

    keep = parser.add_mutually_exclusive_group()
    keep.add_argument("--window", type=int, default=2500,
                      help="keep the last N cycles of the log (the default)")
    keep.add_argument("--chunk", type=int, default=0,
                      help="keep every cycle, N rows per file")

    parser.add_argument("--max-cycles", type=int, default=20_000)
    parser.add_argument("--idle-limit", type=int, default=2_000,
                        help="stop after this many cycles with no progress")
    parser.add_argument("--rob-rows", type=int, default=4,
                        help="how many reorder-buffer entries the log prints")
    parser.add_argument("--waves", action="store_true")
    parser.add_argument("--expect", default="host",
                        help="host (compile and run the same C natively), none, or a file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "sim",
        description = "Compile C programs, build the machine for them once, and "
                      "simulate them until each stops.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="build a machine and simulate ONE program on it")
    run.add_argument("c_sources", nargs="+", metavar="source.c", help="the files of one program")
    run.add_argument("--name", default="", help="names the output directory")
    run.add_argument("--out", default="", help="output directory (default: generated/sim/run/<name>)")
    add_machine_args(run)
    add_program_args(run)

    batch = sub.add_parser("batch", help="build a machine and simulate MANY programs on it, one simulator process")
    batch.add_argument("c_sources", nargs="+", metavar="program.c", help="one file per program")
    batch.add_argument("--suffix", default=None,
                       help="appended to each program's stem to name its run directory "
                            "(default: _<target>_<opt>)")
    add_machine_args(batch)
    add_program_args(batch)
    return parser


# ---- the commands ---------------------------------------------------------------------------

def name_of(args) -> str:
    return args.name or os.path.splitext(os.path.basename(args.c_sources[0]))[0]


def run_dir_of(args, name: str) -> str:
    return getattr(args, "out", "") or str(SIM_ROOT / "run" / name)      # batch has no --out


def build_machine(args) -> SimMachine:
    return SYSTEMS[args.target](imem_bytes=args.imem, dmem_bytes=args.dmem, lanes=args.lanes)


def build_program(machine: SimMachine, args, c_sources: List[str], name: str, run_dir: str) -> SimProgram:
    return build_o3_sim_program(machine, c_sources, run_dir, name,
                                opt          = args.opt,
                                log_enabled  = args.log,
                                log_window   = args.window,
                                log_chunk    = args.chunk,
                                log_rob_rows = args.rob_rows,
                                max_cycles   = args.max_cycles,
                                idle_limit   = args.idle_limit)


def sim_options_of(args) -> SimOptions:
    return SimOptions(sim=args.sim, waves=args.waves, expect=args.expect)


def judge(program: SimProgram, result: RunResult, expect: str) -> Verdict:
    return compare_console(read_expected_text(program.c_sources, expect), result.console)


def cmd_run(args) -> int:
    # --- the machine side: built whole, BEFORE the sim sees anything --------------
    name    = name_of(args)
    machine = build_machine(args)
    program = build_program(machine, args, args.c_sources, name, run_dir_of(args, name))

    # --- the sim side: run it, judge it, report it --------------------------------
    result  = run_batch(SimBatch(machine, (program,)), sim_options_of(args))[name]
    verdict = judge(program, result, args.expect)
    print(describe(program.run_dir, result, verdict))
    return exit_code_for(result, verdict)


def cmd_batch(args) -> int:
    machine  = build_machine(args)
    suffix   = args.suffix if args.suffix is not None else f"_{args.target}_{args.opt.lstrip('-').lower()}"
    programs = []
    for source in args.c_sources:
        name = os.path.splitext(os.path.basename(source))[0] + suffix
        programs.append(build_program(machine, args, [source], name, run_dir_of(args, name)))

    results = run_batch(SimBatch(machine, tuple(programs)), sim_options_of(args))
    worst   = EXIT_OK
    for program in programs:
        result  = results[program.name]
        verdict = judge(program, result, args.expect)
        code    = exit_code_for(result, verdict)
        worst   = max(worst, code)
        print(f"{program.name:<28} {'ok' if code == EXIT_OK else 'FAILED':<7} {result.stop_reason:<11} "
              f"{result.cycles:>9} cycles  exit {result.exit_code}  {verdict.describe()}", flush=True)
    return worst


COMMANDS = {"run": cmd_run, "batch": cmd_batch}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


def run() -> None:
    """Entry point that reports a broken run as a message, not a traceback."""
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        sys.exit(EXIT_HARNESS)
