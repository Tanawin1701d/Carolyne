# The MIPS32 machine runs a hand-assembled program to its exit door — the
# one simulation of this ISA that needs no cross-compiler. Slow: it emits
# the machine and builds a simulator (cached after the first run), in a
# SUBPROCESS for the reason test_sim_e2e.py gives.
#
#     .venv/bin/pytest tests/test_by_ai/test_mips32_smoke.py -m slow

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO   = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "tests" / "sim" / "run_mips_smoke.py"

pytestmark = pytest.mark.slow


def have_sim() -> bool:
    try:
        import cocotb                                                   # noqa: F401
        from kathryn.sim.backend.cocotb import verilator_is_available
    except ImportError:
        return False
    return verilator_is_available()


@pytest.mark.skipif(not have_sim(), reason="needs cocotb and verilator")
def test_a_hand_assembled_program_runs_on_the_mips32_machine():
    env  = {**os.environ,
            "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)}
    done = subprocess.run([sys.executable, str(RUNNER)], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=3600)
    lines  = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, done.stdout[-3000:] + done.stderr[-3000:]
    result = json.loads(lines[-1][len("RESULT "):])
    assert result["stop_reason"] == "exit" and result["exit_code"] == 0, result
    assert result["console"] == "Hi\n4242*"           # the taken branch skipped the bad store
    assert done.returncode == 0
