# The sim end to end: compile hello.c, build the machine, simulate it, and check
# what it printed against a host build of the same source.
#
# Marked `slow` and run in a SUBPROCESS. Kathryn's emitted names come from a
# process-global counter, so a compiled simulator only serves an emit made in
# the same build order — inside one pytest process the ids have already shifted
# and every run would recompile.
#
#     .venv/bin/pytest tests/test_sim_e2e.py -m slow

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
MIPS_GCC = "mipsel-linux-gnu-gcc"

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
needs_mips  = pytest.mark.skipif(not have_tools() or shutil.which(MIPS_GCC) is None,
                                 reason=f"needs the sim tools and {MIPS_GCC}")


def run_cli(*args, name: str) -> subprocess.CompletedProcess:
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)}
    return subprocess.run([sys.executable, "-m", "examples.sim", "run", HELLO,
                           "--name", name, *args],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=3600)


def result_of(name: str) -> dict:
    path = REPO / "generated" / "sim" / "run" / name / "result.json"
    assert path.is_file(), f"the run wrote no result.json at {path}"
    return json.loads(path.read_text())


@needs_tools
def test_hello_reaches_its_exit_door_and_prints_the_right_thing():
    done   = run_cli("--no-log", name="hello_e2e")
    result = result_of("hello_e2e")
    assert result["stop_reason"] == "exit", f"stopped on {result['stop_reason']}\n{done.stdout[-3000:]}"
    assert result["console"]   == WANT
    assert result["exit_code"] == 0
    assert done.returncode == 0


@needs_tools
def test_the_log_writes_a_readable_table_and_the_same_console():
    done   = run_cli("--log", "--window", "400", name="hello_log")
    run    = REPO / "generated" / "sim" / "run" / "hello_log"
    result = result_of("hello_log")
    assert result["console"] == WANT, done.stdout[-3000:]
    trace = (run / "trace.sl").read_text()
    assert "CYCLE/MPFT" in trace and "ROB/COMMIT" in trace
    assert (run / "console.txt").read_text().endswith(WANT)
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    kinds  = {event["kind"] for line in events for event in line["events"]}
    assert "mmio" in kinds and "commit" in kinds


@needs_mips
def test_hello_runs_on_the_mips32_machine_too():
    # the same source, the other ISA: one engine, two descriptions
    done   = run_cli("--no-log", "--target", "mips32", name="hello_mips_e2e")
    result = result_of("hello_mips_e2e")
    assert result["stop_reason"] == "exit", f"stopped on {result['stop_reason']}\n{done.stdout[-3000:]}"
    assert result["console"]   == WANT
    assert result["exit_code"] == 0
    assert done.returncode == 0
