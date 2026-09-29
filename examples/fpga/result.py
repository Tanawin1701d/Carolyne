# The driver's raw outcome rendered into the sim's RunResult, so the report,
# the oracle verdict and the comparison read a board run and a sim run alike.
#
# The console is rendered HERE, with the sim's own ConsoleCapture rules (a
# putchar is one byte, a putint a signed decimal), so the board sends words and
# tags only and cannot disagree with the simulator about what they mean.

from __future__ import annotations

import json
import os
from typing import Optional

from carolyne.debug.log import ConsoleCapture
from examples.fpga.bridge import TAG_PUTINT, HostRunOutcome
from examples.sim.result import RunResult

CONSOLE_FILE = "console.txt"
OUTCOME_FILE = "board_outcome.json"


def render_console(outcome: HostRunOutcome) -> ConsoleCapture:
    console = ConsoleCapture()
    for tag, word in outcome.console:
        if tag == TAG_PUTINT:
            console.put_int(word)
        else:
            console.put_char(word)
    return console


def run_result_of_outcome(outcome: HostRunOutcome, out_dir: str) -> RunResult:
    """The RunResult of one bridge run; writes console.txt beside it."""
    os.makedirs(out_dir, exist_ok=True)
    console = render_console(outcome)
    path    = os.path.join(out_dir, CONSOLE_FILE)
    console.write(path, outcome.cycles)
    return RunResult(stop_reason = outcome.stop_reason,
                     cycles      = outcome.cycles,
                     exit_code   = outcome.exit_code,
                     console     = console.text,
                     files       = {"console": path})


def read_board_outcome(out_dir: str) -> Optional[HostRunOutcome]:
    """The raw outcome a board run left in `out_dir`, or None when there is none.

    - what RunResult does not carry: the overflow and refused-write flags
    """
    path = os.path.join(out_dir, OUTCOME_FILE)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return HostRunOutcome.from_dict(json.load(handle))


def describe_flags(outcome: Optional[HostRunOutcome]) -> str:
    """The bridge's own warnings about a run, one line, or "" when there are none."""
    if outcome is None:
        return ""
    notes = []
    if outcome.console_overflow:
        notes.append(f"console TRUNCATED: the bridge holds {len(outcome.console)} entries, "
                     f"the program printed more (raise --console-depth)")
    if outcome.host_write_refused:
        notes.append("a host write arrived with the read lock open and was dropped")
    return "; ".join(notes)
