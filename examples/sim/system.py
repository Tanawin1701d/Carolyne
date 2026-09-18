# THE CONTRACT — what a machine family hands the simulator. The sim runs ANY
# system built to this shape and reads nothing else of it.
#
# Everything machine-model related is built BEFORE this record exists: the
# emitted Verilog and its manifest (rtl_dir), the loaded program, and the
# cocotb test that knows the machine's probes (test_module). `env` is the
# machine side's own handoff to that test — the sim forwards it UNREAD.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class SimSystem:
    """One ready-to-simulate machine + program, as the sim receives it."""

    name        : str                  # names the run in reports
    run_dir     : str                  # where this run's files go (logs, result.json)
    rtl_dir     : str                  # the emitted top.v and its sim manifest
    test_module : str                  # import path of the cocotb test, from the repo root
    test_case   : str                  # the @cocotb.test() name inside it
    env         : Dict[str, str] = field(default_factory=dict)   # forwarded to the test, unread
    c_sources   : Tuple[str, ...] = ()                           # the program's C files, for the host oracle
