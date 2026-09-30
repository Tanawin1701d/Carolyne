# The sweep: every program of examples/compile_tool/programs through the sim,
# one target, one or more optimisation levels, and a table at the end.
#
#   python -m examples.sim.sweep --target mips32 --opt=-O0 --opt=-O2 --dmem 16384
#   python -m examples.sim.sweep --target rv32im --programs hello.c fib.c
#
# ONE MACHINE, ONE SIMULATOR PROCESS: the machine is emitted once, compiled
# once (or found in the cache), and every program runs in the same cocotb
# process — the test resets the machine between them. What used to be one
# subprocess per program is one batch (examples/sim/runner.py).
#
# The verdict is the sim's own (`--expect host`): a run counts as matched when
# the machine stopped on its exit door, exited 0, and its console equals the
# host build's, byte for byte.

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
from dataclasses import dataclass
from typing import List, Sequence

from examples.compile_tool.cli import parse_size
from examples.compile_tool.layout import DEFAULT_IMEM_BYTES
from examples.o3.sim.system import build_o3_sim_program
from examples.sim.cli import SYSTEMS
from examples.sim.options import SimOptions
from examples.sim.oracle import compare_console, compile_and_run_on_host
from examples.sim.runner import SIM_ROOT, run_batch
from examples.sim.system import SimBatch

REPO     = pathlib.Path(__file__).resolve().parents[2]
PROGRAMS = REPO / "examples" / "compile_tool" / "programs"


@dataclass(frozen=True)
class SweepRow:
    """One run's outcome, as the table prints it."""

    program     : str
    target      : str
    opt         : str
    stop_reason : str
    cycles      : int
    exit_code   : int
    oracle_ok   : bool

    @property
    def matched(self) -> bool:
        return self.stop_reason == "exit" and self.exit_code == 0 and self.oracle_ok


def all_programs() -> List[str]:
    return sorted(str(p) for p in PROGRAMS.glob("*.c"))


def render(rows: Sequence[SweepRow], seconds: float) -> str:
    head = f"{'program':<12} {'target':<7} {'opt':<4} {'stop':<11} {'cycles':>9} {'exit':>4} {'oracle':<8} verdict"
    body = [f"{r.program:<12} {r.target:<7} {r.opt:<4} {r.stop_reason:<11} {r.cycles:>9} "
            f"{r.exit_code:>4} {'same' if r.oracle_ok else 'DIFFERS':<8} {'matched' if r.matched else 'FAILED'}"
            for r in rows]
    matched = sum(r.matched for r in rows)
    return "\n".join([head, *body, f"{matched}/{len(rows)} matched in {seconds:.1f}s, one simulator process"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sweep",
                                     description="run every test program through the sim, on one machine")
    parser.add_argument("--target", default="rv32im", choices=sorted(SYSTEMS))
    parser.add_argument("--opt", action="append", default=None,
                        help="an optimisation level; repeat for several (default -O2)")
    parser.add_argument("--imem", type=parse_size, default=DEFAULT_IMEM_BYTES)
    parser.add_argument("--lanes", type=int, default=2)
    parser.add_argument("--dmem", type=parse_size, default=16384,
                        help="the data memory, bytes: cprime needs 16K")
    parser.add_argument("--sim", default="verilator", choices=("verilator", "icarus"))
    parser.add_argument("--max-cycles", type=int, default=8_000_000)
    parser.add_argument("--idle-limit", type=int, default=2_000)
    parser.add_argument("--programs", nargs="*", default=None,
                        help="program file names under programs/ (default: all)")
    return parser


def main(argv=None) -> int:
    args     = build_parser().parse_args(argv)
    opts     = args.opt or ["-O2"]
    sources  = (all_programs() if not args.programs
                else [str(PROGRAMS / p) if not os.path.isabs(p) else p for p in args.programs])
    started  = time.time()

    machine  = SYSTEMS[args.target](imem_bytes=args.imem, dmem_bytes=args.dmem, lanes=args.lanes)
    programs = []
    for opt in opts:
        for source in sources:
            name = f"{pathlib.Path(source).stem}_{args.target}_{opt.lstrip('-').lower()}"
            programs.append(build_o3_sim_program(machine, [source], str(SIM_ROOT / "run" / name), name,
                                                 opt=opt, log_enabled=False,
                                                 max_cycles=args.max_cycles, idle_limit=args.idle_limit))
    results = run_batch(SimBatch(machine, tuple(programs)), SimOptions(sim=args.sim, expect="host"))

    rows = []
    for program, opt in zip(programs, [opt for opt in opts for _ in sources]):
        result = results[program.name]
        oracle = compare_console(compile_and_run_on_host(program.c_sources), result.console)
        row    = SweepRow(pathlib.Path(program.c_sources[0]).stem, args.target, opt,
                          result.stop_reason, result.cycles, result.exit_code, oracle.ok)
        rows.append(row)
        print(f"{row.program:<12} {opt:<4} {'matched' if row.matched else 'FAILED':<8} "
              f"{row.stop_reason:<11} {row.cycles:>9} cycles", flush=True)
        if not row.matched:
            sys.stderr.write(f"--- {program.name}: {oracle.describe()}\n")
    print()
    print(render(rows, time.time() - started))
    return 0 if all(r.matched for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
