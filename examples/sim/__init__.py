# The universal simulator: run a BUILT system — machine, program and cocotb
# test all made beforehand (examples/o3/rv32im/system.py builds the O3 one) —
# and manage the report. Nothing here is machine model.
#
#   system.py    the contract a machine family builds a SimSystem to
#   runner.py    kathryn's simulator: build, run the system's test, read result.json
#   options.py   what the SIM varies (backend, waves, what to expect)
#   result.py    what a run produced
#   oracle.py    what it SHOULD have produced, from a host build of the same C
#   report.py    the printed summary and the process exit code
#   host/        the host stand-in for the generated carolyne_io.h
#   cli.py       the command line, and the one table that names machine families
#
# Usage:
#     python -m examples.sim run examples/compile_tool/programs/hello.c

from __future__ import annotations

from .options import SimOptions
from .oracle  import (Verdict, compare_console, compile_and_run_on_host,
                      read_expected_text)
from .result  import RunResult, read_result
from .runner  import run_system
from .system  import SimSystem

__all__ = ["SimSystem", "SimOptions", "run_system",
           "RunResult", "read_result",
           "Verdict", "compare_console", "compile_and_run_on_host",
           "read_expected_text"]
