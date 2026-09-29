# The board in simulation, end to end: hello.c through the HostBridge with the
# board's own driver, and the cycle count held EQUAL to the plain simulator's
# — the pin the sim-vs-board comparison leans on.
#
# Marked `slow` and run in SUBPROCESSES, for the reason test_sim_e2e.py gives.

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from examples.sim.oracle import host_compiler

REPO  = pathlib.Path(__file__).resolve().parents[2]
HELLO = "examples/compile_tool/programs/hello.c"
WANT  = "hello from carolyne\n0\n1\n4\n9\n16\n"

pytestmark = pytest.mark.slow


def have_tools() -> bool:
    try:
        import cocotb                                                   # noqa: F401
        from kathryn.sim.backend.cocotb import verilator_is_available
    except ImportError:
        return False
    return (verilator_is_available() and host_compiler() is not None
            and shutil.which("riscv64-unknown-elf-gcc") is not None)


needs_tools = pytest.mark.skipif(not have_tools(),
                                 reason="needs cocotb, verilator, riscv gcc and a host cc")


def run_module(module: str, *args) -> subprocess.CompletedProcess:
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)}
    return subprocess.run([sys.executable, "-m", module, *args],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=3600)


def read_result(path: pathlib.Path) -> dict:
    assert path.is_file(), f"the run wrote no result.json at {path}"
    return json.loads(path.read_text())


@needs_tools
def test_hello_through_the_bridge_matches_the_plain_simulation_cycle_for_cycle():
    done   = run_module("examples.fpga", "simrun", HELLO, "--dmem", "16384",
                        "--cycle-limit", "20000", "--name", "hello_bridge_e2e")
    bridge = read_result(REPO / "generated" / "fpga" / "run" / "hello_bridge_e2e" / "sim" / "result.json")
    assert bridge["stop_reason"] == "exit", f"stopped on {bridge['stop_reason']}\n{done.stdout[-3000:]}"
    assert bridge["console"]   == WANT
    assert bridge["exit_code"] == 0
    assert done.returncode == 0, done.stdout[-3000:]

    plain = run_module("examples.sim", "run", HELLO, "--dmem", "16384", "--no-log",
                       "--expect", "none", "--name", "hello_bridge_ref")
    ref   = read_result(REPO / "generated" / "sim" / "run" / "hello_bridge_ref" / "result.json")
    assert plain.returncode == 0, plain.stdout[-3000:]
    assert bridge["cycles"] == ref["cycles"]
