# THE REPORT — what a finished run tells the caller: the printed summary and
# the process exit code, kept apart because a wrong ANSWER and a broken
# HARNESS are different failures.

from __future__ import annotations

from examples.sim.oracle import Verdict
from examples.sim.result import RunResult
from examples.sim.system import SimSystem

EXIT_OK      = 0
EXIT_HARNESS = 1
EXIT_WRONG   = 2


def describe(system: SimSystem, result: RunResult, verdict: Verdict) -> str:
    """The summary a run prints: the console, then what happened to it."""
    run_dir = system.run_dir
    lines   = ["----- output -----", result.console.rstrip("\n"), "",
               f"stopped   : {result.stop_reason} after {result.cycles} cycles",
               f"exit code : {result.exit_code}",
               verdict.describe(),
               f"files     : {run_dir}"]
    return "\n".join(lines)


def exit_code_for(result: RunResult, verdict: Verdict) -> int:
    """0 only when the program reached its exit door AND printed the right thing."""
    if result.stopped_at_exit and verdict.ok and result.exit_code == 0:
        return EXIT_OK
    return EXIT_WRONG
