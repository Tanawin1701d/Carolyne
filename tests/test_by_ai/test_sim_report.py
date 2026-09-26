# The sim's own half: the command line, the verdict and the oracle. No machine
# model anywhere — that is the point of the split.

from __future__ import annotations

import pytest

from examples.sim.cli import build_parser, name_of, run_dir_of
from examples.sim.oracle import compare_console, compile_and_run_on_host, host_compiler
from examples.sim.report import EXIT_OK, EXIT_WRONG, exit_code_for
from examples.sim.result import RunResult

HELLO = "examples/compile_tool/programs/hello.c"


# ---- the command line --------------------------------------------------------------

def test_logging_is_on_unless_it_is_turned_off():
    assert build_parser().parse_args(["run", HELLO]).log is True
    assert build_parser().parse_args(["run", HELLO, "--no-log"]).log is False


def test_a_window_and_a_chunk_cannot_both_be_asked_for():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", HELLO, "--window", "10", "--chunk", "10"])


def test_the_run_directory_is_named_after_the_first_source():
    args = build_parser().parse_args(["run", "some/dir/prog.c"])
    name = name_of(args)
    assert name == "prog" and run_dir_of(args, name).endswith("run/prog")
    named = build_parser().parse_args(["run", HELLO, "--name", "x"])
    assert name_of(named) == "x"


def test_a_target_with_no_system_is_refused_at_the_parser():
    # both machine families are systems now; a target nothing builds is not
    for target in ("rv32im", "mips32"):
        assert build_parser().parse_args(["run", HELLO, "--target", target]).target == target
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", HELLO, "--target", "arm"])


# ---- the verdict ---------------------------------------------------------------------

def test_a_matching_console_is_the_only_way_to_exit_zero():
    good = RunResult("exit", 100, 0, "hi")
    assert exit_code_for(good, compare_console("hi", "hi")) == EXIT_OK
    assert exit_code_for(good, compare_console("ho", "hi")) == EXIT_WRONG
    assert exit_code_for(RunResult("idle", 100, None, "hi"), compare_console("hi", "hi")) == EXIT_WRONG
    assert exit_code_for(RunResult("exit", 100, 3, "hi"), compare_console("hi", "hi")) == EXIT_WRONG


def test_a_difference_says_where_it_starts():
    verdict = compare_console("hello\n", "he\x00lo\n")
    assert not verdict.ok and "at byte 2" in verdict.detail


def test_a_short_console_says_it_ended_early():
    verdict = compare_console("hello", "hel")
    assert not verdict.ok and "ends at byte 3" in verdict.detail


def test_an_unchecked_console_always_passes():
    assert compare_console(None, "anything").ok


# ---- the oracle -------------------------------------------------------------------------

@pytest.mark.skipif(host_compiler() is None, reason="no host C compiler")
def test_the_host_build_of_hello_says_what_the_machine_must_print():
    assert compile_and_run_on_host([HELLO]) == "hello from carolyne\n0\n1\n4\n9\n16\n"
