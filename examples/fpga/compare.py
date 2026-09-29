# THE COMPARISON — a program's sim run against its board run. The memories sit
# inside the design with the simulator's timing, so the two must agree on
# everything: the console, the exit code, how the run stopped, and the EXACT
# cycle count. A cycle difference is a finding, not noise.

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from examples.sim.oracle import Verdict, compare_console
from examples.sim.result import RunResult

COMPARE_FILE = "compare.json"


@dataclass(frozen=True)
class RunComparison:
    """Where a sim run and a board run agree, field by field."""

    sim            : RunResult
    board          : RunResult
    console        : Verdict
    stop_reason_ok : bool
    exit_code_ok   : bool
    cycles_ok      : bool

    @property
    def ok(self) -> bool:
        return self.console.ok and self.stop_reason_ok and self.exit_code_ok and self.cycles_ok

    def describe(self) -> str:
        def row(what, sim, board, ok):
            return f"  {what:<12} sim {sim!s:<14} board {board!s:<14} {'same' if ok else 'DIFFERS'}"
        lines = ["sim vs board: " + ("MATCH" if self.ok else "MISMATCH"),
                 row("stop",      self.sim.stop_reason, self.board.stop_reason, self.stop_reason_ok),
                 row("exit code", self.sim.exit_code,   self.board.exit_code,   self.exit_code_ok),
                 row("cycles",    self.sim.cycles,      self.board.cycles,      self.cycles_ok),
                 f"  {'console':<12} " + ("same" if self.console.ok else f"DIFFERS — {self.console.detail}")]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"ok"             : self.ok,
                "sim"            : asdict(self.sim),
                "board"          : asdict(self.board),
                "console_ok"     : self.console.ok,
                "console_detail" : self.console.detail,
                "stop_reason_ok" : self.stop_reason_ok,
                "exit_code_ok"   : self.exit_code_ok,
                "cycles_ok"      : self.cycles_ok}


def compare_runs(sim: RunResult, board: RunResult) -> RunComparison:
    return RunComparison(sim            = sim,
                         board          = board,
                         console        = compare_console(sim.console, board.console),
                         stop_reason_ok = sim.stop_reason == board.stop_reason,
                         exit_code_ok   = sim.exit_code   == board.exit_code,
                         cycles_ok      = sim.cycles      == board.cycles)


def write_comparison(path: str, comparison: RunComparison) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(comparison.to_dict(), handle, indent=1)
