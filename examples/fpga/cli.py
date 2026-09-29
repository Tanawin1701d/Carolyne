# The command line over the FPGA flow. The SYSTEMS table is the ONE place a
# machine family is named — the flow's own modules read none of it.
#
#   python -m examples.fpga simrun  examples/compile_tool/programs/hello.c
#   python -m examples.fpga compare --sim a/result.json --board b/result.json

from __future__ import annotations

import argparse
import os
import sys

from examples.compile_tool.cli import parse_size
from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from examples.fpga.board import read_board_link
from examples.fpga.compare import COMPARE_FILE, compare_runs, write_comparison
from examples.fpga.options import FpgaOptions
from examples.fpga.result import describe_flags, read_board_outcome
from examples.fpga.runner import (FPGA_ROOT, build_bitstream, describe_bitstream, run_in_simulation,
                                  run_on_board, run_plain_simulation)
from examples.fpga.system import FpgaSystem
from examples.o3.core.fpga_system import (DEFAULT_CONSOLE_DEPTH, DEFAULT_CYCLE_LIMIT,
                                          DEFAULT_TIMEOUT_S, build_o3_fpga_program)
from examples.o3.mips32.system import build_fpga_machine as build_mips32_machine
from examples.o3.rv32im.system import build_fpga_machine as build_rv32im_machine
from examples.sim.options import SimOptions
from examples.sim.oracle import compare_console, read_expected_text
from examples.sim.report import EXIT_HARNESS, describe, exit_code_for
from examples.sim.result import read_result

SYSTEMS = {"rv32im": build_rv32im_machine, "mips32": build_mips32_machine}


# ---- the parser ---------------------------------------------------------------------

def add_machine_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", default="rv32im", choices=sorted(SYSTEMS))
    parser.add_argument("--imem", type=parse_size, default=DEFAULT_IMEM_BYTES)
    parser.add_argument("--dmem", type=parse_size, default=DEFAULT_DMEM_BYTES)
    parser.add_argument("--lanes", type=int, default=2)
    parser.add_argument("--console-depth", type=int, default=DEFAULT_CONSOLE_DEPTH,
                        help="console entries the bridge captures (power of two)")


def add_program_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("c_sources", nargs="+", metavar="source.c")
    parser.add_argument("--name", default="", help="names the output directory")
    parser.add_argument("--opt", default="-O2")
    parser.add_argument("--out", default="", help="output directory (default: generated/fpga/run/<name>)")
    parser.add_argument("--cycle-limit", type=int, default=DEFAULT_CYCLE_LIMIT,
                        help="the bridge stops the machine after this many cycles; 0 = never")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                        help="seconds the host waits for the exit door on the board")
    parser.add_argument("--expect", default="host",
                        help="host (compile and run the same C natively), none, or a file")


def add_backend_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", default="vivado")
    parser.add_argument("--board", default="kv260")
    parser.add_argument("--clock-mhz", type=int, default=50)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--synth-only", action="store_true",
                        help="stop after synthesis: reports only, no bitstream")
    parser.add_argument("--allow-timing-failure", action="store_true",
                        help="deploy a bitstream that missed timing")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "fpga",
        description = "Take an O3 machine to a bitstream, run programs on the board, "
                      "and compare with the simulator.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="emit a machine with its HostBridge and build its bitstream")
    add_machine_args(build)
    add_backend_args(build)

    run = sub.add_parser("run", help="build the bitstream (or reuse it) and run a program on the board")
    add_machine_args(run)
    add_program_args(run)
    add_backend_args(run)
    run.add_argument("--board-link", default=None, help="the board login file (default: board.local.json)")
    run.add_argument("--compare-sim", action="store_true",
                     help="also run the plain simulator and compare console, exit code and cycles")

    simrun = sub.add_parser("simrun", help="run a program through the simulated HostBridge")
    add_machine_args(simrun)
    add_program_args(simrun)
    simrun.add_argument("--sim", default="verilator", choices=("verilator", "icarus"))
    simrun.add_argument("--waves", action="store_true")

    compare = sub.add_parser("compare", help="compare two result.json files, sim against board")
    compare.add_argument("--sim",   required=True, metavar="result.json")
    compare.add_argument("--board", required=True, metavar="result.json")
    compare.add_argument("--out", default="", help=f"where to write {COMPARE_FILE}")
    return parser


# ---- the commands --------------------------------------------------------------------

def name_of(args) -> str:
    return args.name or os.path.splitext(os.path.basename(args.c_sources[0]))[0]


def run_dir_of(args, name: str) -> str:
    return args.out or str(FPGA_ROOT / "run" / name)


def build_machine(args):
    return SYSTEMS[args.target](imem_bytes    = args.imem,
                                dmem_bytes    = args.dmem,
                                lanes         = args.lanes,
                                console_depth = args.console_depth)


def fpga_options_of(args) -> FpgaOptions:
    return FpgaOptions(backend              = args.backend,
                       board                = args.board,
                       clock_mhz            = args.clock_mhz,
                       jobs                 = args.jobs,
                       synth_only           = args.synth_only,
                       allow_timing_failure = args.allow_timing_failure,
                       expect               = getattr(args, "expect", "host"))


def build_system(args) -> FpgaSystem:
    """The machine side, built whole before the flow sees anything."""
    name    = name_of(args)
    machine = build_machine(args)
    program = build_o3_fpga_program(machine, args.c_sources, run_dir_of(args, name), name,
                                    opt         = args.opt,
                                    cycle_limit = args.cycle_limit,
                                    timeout_s   = args.timeout)
    return FpgaSystem(machine, program)


def judge(system: FpgaSystem, result, expect: str, run_dir: str) -> int:
    verdict = compare_console(read_expected_text(system.program.c_sources, expect), result.console)
    print(describe(run_dir, result, verdict))
    return exit_code_for(result, verdict)


def cmd_build(args) -> int:
    bitstream = build_bitstream(build_machine(args), fpga_options_of(args))
    print(describe_bitstream(bitstream))
    return 0 if (bitstream.timing_met is not False or args.allow_timing_failure or args.synth_only) else 2


def cmd_run(args) -> int:
    options   = fpga_options_of(args)
    link      = read_board_link(args.board_link)
    system    = build_system(args)
    bitstream = build_bitstream(system.machine, options)
    print(describe_bitstream(bitstream), flush=True)
    result    = run_on_board(system, bitstream, link, options)
    board_dir = os.path.join(system.program.run_dir, "board")
    code      = judge(system, result, args.expect, board_dir)
    flags     = describe_flags(read_board_outcome(board_dir))
    if flags:
        print(f"bridge    : {flags}")
    if args.compare_sim:
        sim        = run_plain_simulation(system.program, args.target, args.dmem, args.lanes,
                                          args.opt, args.cycle_limit)
        comparison = compare_runs(sim, result)
        write_comparison(os.path.join(system.program.run_dir, COMPARE_FILE), comparison)
        print(comparison.describe())
        code = code or (0 if comparison.ok else 2)
    return code


def cmd_simrun(args) -> int:
    system = build_system(args)
    result = run_in_simulation(system, SimOptions(sim=args.sim, waves=args.waves, expect=args.expect))
    return judge(system, result, args.expect, os.path.join(system.program.run_dir, "sim"))


def cmd_compare(args) -> int:
    comparison = compare_runs(read_result(args.sim), read_result(args.board))
    print(comparison.describe())
    if args.out:
        write_comparison(os.path.join(args.out, COMPARE_FILE), comparison)
    return 0 if comparison.ok else 2


COMMANDS = {"build": cmd_build, "run": cmd_run, "simrun": cmd_simrun, "compare": cmd_compare}


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
