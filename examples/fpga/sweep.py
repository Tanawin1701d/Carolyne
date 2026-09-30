# The board sweep: every program of examples/compile_tool/programs on ONE
# bitstream, in ONE board session, with the host oracle's verdict for each and
# — with --compare-sim — the plain simulator's cycle count beside the board's.
#
#   python -m examples.fpga.sweep --target rv32im --dmem 16384 --compare-sim
#   python -m examples.fpga.sweep --programs hello.c fib.c
#
# The machine is emitted once and the bitstream built (or found) once; the
# programs are compiled here and uploaded together. The reference simulations
# run one subprocess each, for the reason examples/sim/sweep.py gives.

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from examples.compile_tool.cli import parse_size
from examples.fpga.cli import (SYSTEMS, add_backend_args, build_machine, fpga_options_of)
from examples.fpga.compare import COMPARE_FILE, compare_runs, write_comparison
from examples.fpga.runner import (FPGA_ROOT, build_bitstream, describe_bitstream, run_many_on_board,
                                  run_plain_simulations)
from examples.fpga.board import read_board_link
from examples.fpga.result import read_board_outcome
from examples.o3.fpga.system import DEFAULT_CONSOLE_DEPTH, DEFAULT_CYCLE_LIMIT, build_o3_fpga_program
from examples.sim.oracle import compare_console, compile_and_run_on_host

REPO     = pathlib.Path(__file__).resolve().parents[2]
PROGRAMS = REPO / "examples" / "compile_tool" / "programs"


@dataclass(frozen=True)
class SweepRow:
    """One program's outcome on the board, as the table prints it."""

    program     : str
    stop_reason : str
    cycles      : int
    exit_code   : Optional[int]
    oracle_ok   : bool
    sim_cycles  : Optional[int]        # None when the sim was not run
    truncated   : bool = False         # the bridge's console capture overflowed

    @property
    def cycles_ok(self) -> bool: return self.sim_cycles is None or self.sim_cycles == self.cycles

    @property
    def matched(self) -> bool:
        return self.stop_reason == "exit" and self.exit_code == 0 and self.oracle_ok and self.cycles_ok

    @property
    def oracle_word(self) -> str:
        if self.oracle_ok:  return "same"
        if self.truncated:  return "TRUNC"     # the console was cut by the capture, not wrong
        return "DIFFERS"


def all_programs() -> List[str]:
    return sorted(str(p) for p in PROGRAMS.glob("*.c"))


def render(rows: Sequence[SweepRow], with_sim: bool) -> str:
    head = f"{'program':<12} {'stop':<11} {'cycles':>9} {'exit':>5} {'oracle':<8}"
    if with_sim:
        head += f" {'sim cycles':>10} {'delta':>7}"
    head += "  verdict"
    body = []
    for r in rows:
        line = (f"{r.program:<12} {r.stop_reason:<11} {r.cycles:>9} {str(r.exit_code):>5} "
                f"{r.oracle_word:<8}")
        if with_sim:
            sim   = "-" if r.sim_cycles is None else str(r.sim_cycles)
            delta = "-" if r.sim_cycles is None else str(r.cycles - r.sim_cycles)
            line += f" {sim:>10} {delta:>7}"
        body.append(line + f"  {'matched' if r.matched else 'FAILED'}")
    matched = sum(r.matched for r in rows)
    return "\n".join([head, *body, f"{matched}/{len(rows)} matched"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fpga sweep",
                                     description="run every test program on the board, on one bitstream")
    parser.add_argument("--target", default="rv32im", choices=sorted(SYSTEMS))
    parser.add_argument("--opt", default="-O2")
    parser.add_argument("--imem", type=parse_size, default=8192)
    parser.add_argument("--dmem", type=parse_size, default=16384, help="the data memory, bytes: cprime needs 16K")
    parser.add_argument("--lanes", type=int, default=2)
    parser.add_argument("--console-depth", type=int, default=DEFAULT_CONSOLE_DEPTH)
    parser.add_argument("--cycle-limit", type=int, default=DEFAULT_CYCLE_LIMIT)
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds the board waits per program")
    parser.add_argument("--programs", nargs="*", default=None,
                        help="program file names under programs/ (default: all)")
    parser.add_argument("--compare-sim", action="store_true",
                        help="also run each program in the plain simulator and compare the cycle counts")
    parser.add_argument("--board-link", default=None, help="the board login file (default: board.local.json)")
    add_backend_args(parser)
    return parser


def main(argv=None) -> int:
    args     = build_parser().parse_args(argv)
    programs = (all_programs() if not args.programs
                else [str(PROGRAMS / p) if not os.path.isabs(p) else p for p in args.programs])
    options  = fpga_options_of(args)
    link     = read_board_link(args.board_link)

    machine   = build_machine(args)
    bitstream = build_bitstream(machine, options)
    print(describe_bitstream(bitstream), flush=True)

    tag   = args.opt.lstrip("-").lower()
    built = [build_o3_fpga_program(machine, [source], str(FPGA_ROOT / "run" / f"{pathlib.Path(source).stem}_{args.target}_{tag}"),
                                   f"{pathlib.Path(source).stem}_{args.target}_{tag}",
                                   opt=args.opt, cycle_limit=args.cycle_limit, timeout_s=args.timeout)
             for source in programs]
    started = time.time()
    results = run_many_on_board(machine, built, bitstream, link, options)
    print(f"board session: {len(built)} programs in {time.time() - started:.1f}s", flush=True)

    sims = {}
    if args.compare_sim:                     # every reference in ONE simulator process
        started = time.time()
        sims    = run_plain_simulations(built, args.target, args.dmem, args.lanes, args.opt, args.cycle_limit)
        print(f"simulator session: {len(built)} programs in {time.time() - started:.1f}s", flush=True)

    rows = []
    for program in built:
        result   = results[program.name]
        expected = compile_and_run_on_host(program.c_sources)
        oracle   = compare_console(expected, result.console)
        sim      = sims.get(program.name)
        if sim is not None:
            write_comparison(os.path.join(program.run_dir, COMPARE_FILE), compare_runs(sim, result))
        outcome = read_board_outcome(os.path.join(program.run_dir, "board"))
        row     = SweepRow(pathlib.Path(program.c_sources[0]).stem, result.stop_reason, result.cycles,
                           result.exit_code, oracle.ok, None if sim is None else sim.cycles,
                           truncated=bool(outcome and outcome.console_overflow))
        rows.append(row)
        print(f"{row.program:<12} {'matched' if row.matched else 'FAILED':<8} {row.stop_reason:<11} "
              f"{row.cycles:>9} cycles" + ("" if sim is None else f"  (sim {sim.cycles})")
              + ("  console truncated" if row.truncated else ""), flush=True)
    print()
    print(render(rows, args.compare_sim))
    return 0 if all(r.matched for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
