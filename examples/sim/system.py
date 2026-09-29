# THE CONTRACT — what a machine family hands the simulator. The sim runs ANY
# system built to this shape and reads nothing else of it.
#
# Everything machine-model related is built BEFORE these records exist: the
# emitted Verilog and its manifest (rtl_dir), the loaded programs, and the
# cocotb test that knows the machine's probes (test_module). A program's `env`
# is the machine side's own handoff to that test — the sim forwards it UNREAD.
#
# ONE MACHINE, MANY PROGRAMS: a SimMachine is emitted and compiled once, and a
# SimBatch runs every SimProgram on it in ONE simulator process — the test
# resets the machine, loads the next images and runs again, the way the C++
# simulator looped over its test cases. A SimSystem is the one-program form.
#
# The batch crosses to the simulator process as one JSON file
# (write_sim_batch / read_sim_batch, named by $CAROLYNE_SIM_BATCH) holding each
# program's name, run dir and env — the test reads its own handoff out of each.

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

BATCH_ENV  = "CAROLYNE_SIM_BATCH"      # names the batch file inside the simulator process
BATCH_FILE = "sim_batch.json"


@dataclass(frozen=True)
class SimMachine:
    """One emitted machine, and the test that knows how to run it."""

    label        : str                  # names the machine in paths and reports
    target       : str                  # the compile_tool target its programs are built for
    rtl_dir      : str                  # the emitted top.v and its sim manifest
    test_module  : str                  # import path of the cocotb test, from the repo root
    test_case    : str                  # the @cocotb.test() name inside it
    config_knobs : Dict[str, int] = field(default_factory=dict)   # what the family's config builder was called with
    config       : Any = field(default=None, compare=False, repr=False)   # in-process only


@dataclass(frozen=True)
class SimProgram:
    """One program laid out for a machine, as the sim receives it."""

    name      : str                     # names the run in reports and its directory
    run_dir   : str                     # where this run's files go (logs, result.json)
    env       : Dict[str, str]  = field(default_factory=dict)   # forwarded to the test, unread
    c_sources : Tuple[str, ...] = ()                            # the program's C files, for the host oracle


@dataclass(frozen=True)
class SimBatch:
    """The machine and every program one simulator process runs on it."""

    machine  : SimMachine
    programs : Tuple[SimProgram, ...]


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

    def as_batch(self) -> SimBatch:
        """The same run as a batch of one: the runner has one code path."""
        machine = SimMachine(label=self.name, target="", rtl_dir=self.rtl_dir,
                             test_module=self.test_module, test_case=self.test_case)
        return SimBatch(machine, (SimProgram(self.name, self.run_dir, dict(self.env), self.c_sources),))


# ---- crossing the process boundary ------------------------------------------------

def write_sim_batch(path: str, batch: SimBatch) -> None:
    """The programs of a batch, as the simulator process reads them."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"machine": batch.machine.label,
                   "programs": [{"name": p.name, "run_dir": p.run_dir, "env": dict(p.env)}
                                for p in batch.programs]},
                  handle, indent=1)


def read_sim_batch(path: Optional[str] = None) -> List[dict]:
    """The batch file at `path`, or the one $CAROLYNE_SIM_BATCH names: one dict per program.

    - None when neither is given: the test then runs the single program its own
      environment describes
    """
    path = path or os.environ.get(BATCH_ENV)
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)["programs"]
