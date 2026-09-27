# The sweep: every program of examples/compile_tool/programs through the sim,
# one target, one or more optimisation levels, and a table at the end.
#
#   python -m examples.sim.sweep --target mips32 --opt=-O0 --opt=-O2 --dmem 16384
#   python -m examples.sim.sweep --target rv32im --programs hello.c fib.c
#
# ONE SUBPROCESS PER PROGRAM: Kathryn's emitted names come from a
# process-global counter, so a compiled simulator only serves an emit made
# in the same build order — a second emit in one process would miss the
# build cache and recompile for minutes. The runs go one after another for
# the same reason: two at once would race the cache directory.
#
# The verdict is the sim's own (`--expect host`): a run counts as matched
# when the machine stopped on its exit door and its console equals the host
# build's, byte for byte.

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Sequence

from examples.compile_tool.cli import parse_size
from examples.sim.runner import SIM_ROOT

REPO     = pathlib.Path(__file__).resolve().parents[2]
PROGRAMS = REPO / "examples" / "compile_tool" / "programs"


@dataclass(frozen=True)
class SweepRow:
    """One run's outcome, as the table prints it."""

    program     : str
    target      : str
    opt         : str
    stop_reason : str        # exit / watchdog / limit / (no result)
    cycles      : int
    exit_code   : int
    cli_rc      : int        # the sim's own verdict: 0 is matched
    seconds     : float

    @property
    def matched(self) -> bool: return self.cli_rc == 0 and self.stop_reason == "exit"


def all_programs() -> List[str]:
    return sorted(str(p) for p in PROGRAMS.glob("*.c"))


def run_one(program: str, target: str, opt: str, lanes: int, dmem: int,
            sim: str, max_cycles: int) -> SweepRow:
    """One program through `python -m examples.sim run`, in its own process."""
    stem = pathlib.Path(program).stem
    name = f"{stem}_{target}_{opt.lstrip('-').lower()}"
    argv = [sys.executable, "-m", "examples.sim", "run", program,
            "--target", target, f"--opt={opt}", "--lanes", str(lanes),
            "--dmem", str(dmem), "--sim", sim, "--max-cycles", str(max_cycles),
            "--no-log", "--expect", "host", "--name", name]
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)}
    started = time.time()
    done    = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, text=True)
    seconds = time.time() - started

    result_path = SIM_ROOT / "run" / name / "result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text())
        row = SweepRow(stem, target, opt, result["stop_reason"], result["cycles"],
                       result["exit_code"], done.returncode, seconds)
    else:
        row = SweepRow(stem, target, opt, "(no result)", 0, -1, done.returncode, seconds)
    if not row.matched:
        sys.stderr.write(f"--- {name}: rc {done.returncode}\n{done.stdout[-2000:]}{done.stderr[-2000:]}\n")
    return row


def render(rows: Sequence[SweepRow]) -> str:
    head = f"{'program':<12} {'target':<7} {'opt':<4} {'stop':<11} {'cycles':>9} {'exit':>4} {'sec':>7}  verdict"
    body = [f"{r.program:<12} {r.target:<7} {r.opt:<4} {r.stop_reason:<11} {r.cycles:>9} "
            f"{r.exit_code:>4} {r.seconds:>7.1f}  {'matched' if r.matched else 'FAILED'}"
            for r in rows]
    matched = sum(r.matched for r in rows)
    return "\n".join([head, *body, f"{matched}/{len(rows)} matched"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sweep",
                                     description="run every test program through the sim")
    parser.add_argument("--target", default="rv32im")
    parser.add_argument("--opt", action="append", default=None,
                        help="an optimisation level; repeat for several (default -O2)")
    parser.add_argument("--lanes", type=int, default=2)
    parser.add_argument("--dmem", type=parse_size, default=16384,
                        help="the data memory, bytes: cprime needs 16K")
    parser.add_argument("--sim", default="verilator", choices=("verilator", "icarus"))
    parser.add_argument("--max-cycles", type=int, default=8_000_000)
    parser.add_argument("--programs", nargs="*", default=None,
                        help="program file names under programs/ (default: all)")
    return parser


def main(argv=None) -> int:
    args     = build_parser().parse_args(argv)
    opts     = args.opt or ["-O2"]
    programs = (all_programs() if not args.programs
                else [str(PROGRAMS / p) if not os.path.isabs(p) else p for p in args.programs])
    rows = []
    for opt in opts:
        for program in programs:
            row = run_one(program, args.target, opt, args.lanes, args.dmem, args.sim,
                          args.max_cycles)
            rows.append(row)
            print(f"{row.program:<12} {opt:<4} {'matched' if row.matched else 'FAILED':<8} "
                  f"{row.stop_reason:<11} {row.cycles:>9} cycles  {row.seconds:.1f}s", flush=True)
    print()
    print(render(rows))
    return 0 if all(r.matched for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
