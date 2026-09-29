# The sim-vs-board comparison and the command line's shape.

from __future__ import annotations

import json

from examples.fpga.cli import build_parser
from examples.fpga.compare import compare_runs, write_comparison
from examples.fpga.sweep import SweepRow, render
from examples.sim.result import RunResult


def a_result(**changes) -> RunResult:
    base = dict(stop_reason="exit", cycles=244, exit_code=0, console="hello\n", files={})
    return RunResult(**{**base, **changes})


def test_identical_runs_match_on_every_field():
    comparison = compare_runs(a_result(), a_result())
    assert comparison.ok
    assert "MATCH" in comparison.describe() and "DIFFERS" not in comparison.describe()


def test_a_cycle_difference_alone_is_a_mismatch(tmp_path):
    comparison = compare_runs(a_result(), a_result(cycles=245))
    assert not comparison.ok and comparison.console.ok and not comparison.cycles_ok
    assert "cycles" in comparison.describe() and "DIFFERS" in comparison.describe()
    path = tmp_path / "compare.json"
    write_comparison(str(path), comparison)
    data = json.loads(path.read_text())
    assert data["ok"] is False and data["cycles_ok"] is False and data["board"]["cycles"] == 245


def test_a_console_difference_names_the_byte():
    comparison = compare_runs(a_result(), a_result(console="hallo\n"))
    assert not comparison.console.ok and "at byte 1" in comparison.console.detail


def test_the_sweep_table_judges_exit_oracle_and_cycles():
    rows = [SweepRow("hello", "exit", 244, 0, True, 244),
            SweepRow("fib",   "exit", 3151, 0, True, 3150),
            SweepRow("hanoi", "max_cycles", 8000000, None, False, None)]
    table = render(rows, with_sim=True)
    assert "1/3 matched" in table
    assert rows[0].matched and not rows[1].matched and not rows[2].matched
    assert render(rows[:1], with_sim=False).endswith("1/1 matched")


def test_the_command_line_has_the_four_commands_with_their_defaults():
    parser = build_parser()
    build  = parser.parse_args(["build", "--synth-only"])
    assert build.command == "build" and build.synth_only and build.clock_mhz == 50 and build.board == "kv260"
    simrun = parser.parse_args(["simrun", "hello.c", "--dmem", "16K"])
    assert simrun.dmem == 16384 and simrun.target == "rv32im" and simrun.sim == "verilator"
    run = parser.parse_args(["run", "hello.c", "--compare-sim"])
    assert run.compare_sim and run.board_link is None and run.expect == "host"
    compare = parser.parse_args(["compare", "--sim", "a.json", "--board", "b.json"])
    assert compare.sim == "a.json" and compare.board == "b.json"
