# THE ORACLE — what the program SHOULD print, obtained by compiling the same C
# for the host and running it.
#
# The host header (host/carolyne_io.h) defines the same four calls the
# generated one does, so one source file serves both: the machine's answer is
# checked against a real execution of the same program, not against a string
# somebody typed into a test.
#
# LIMIT: this only works for a program whose output does not depend on the
# machine (no timing, no register width games). `--expect FILE` and
# `--expect none` are the ways out.

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional, Sequence

HOST_INCLUDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host")


@dataclass(frozen=True)
class Verdict:
    """Whether the machine printed what the program should print."""

    ok       : bool
    expected : Optional[str]
    actual   : str
    detail   : str = ""

    def describe(self) -> str:
        if self.expected is None:
            return "console: not checked"
        return "console: MATCHES the host run" if self.ok else f"console: DIFFERS — {self.detail}"


def host_compiler() -> Optional[str]:
    return shutil.which("cc") or shutil.which("gcc")


def compile_and_run_on_host(c_sources: Sequence[str], opt: str = "-O0") -> str:
    """Compile the C files for the host and run them; its stdout is what the
    machine must print."""
    compiler = host_compiler()
    if compiler is None:
        raise RuntimeError("no host C compiler (cc or gcc) to build the oracle with")
    with tempfile.TemporaryDirectory() as work:
        binary = os.path.join(work, "oracle")
        build  = subprocess.run([compiler, opt, f"-I{HOST_INCLUDE}", "-o", binary, *c_sources],
                                capture_output=True, text=True)
        if build.returncode:
            raise RuntimeError(f"the oracle did not compile:\n{build.stderr}")
        run = subprocess.run([binary], capture_output=True, text=True, timeout=60)
        return run.stdout


def compare_console(expected: Optional[str], actual: str) -> Verdict:
    """The two strings, and where they first differ."""
    if expected is None:
        return Verdict(ok=True, expected=None, actual=actual)
    if expected == actual:
        return Verdict(ok=True, expected=expected, actual=actual)
    return Verdict(ok=False, expected=expected, actual=actual,
                   detail=first_difference(expected, actual))


def first_difference(expected: str, actual: str) -> str:
    """Where the two strings part, as an offset and the two characters."""
    for offset, (want, got) in enumerate(zip(expected, actual)):
        if want != got:
            return (f"at byte {offset}: expected {want!r}, got {got!r}"
                    f" (expected {expected!r}, got {actual!r})")
    shorter, longer = ("actual", "expected") if len(actual) < len(expected) else ("expected", "actual")
    return (f"{shorter} ends at byte {min(len(expected), len(actual))}, {longer} continues"
            f" (expected {expected!r}, got {actual!r})")


def read_expected_text(c_sources: Sequence[str], expect: str) -> Optional[str]:
    """What the program should print: the host run, a file, or nothing to check."""
    if expect == "none":
        return None
    if expect == "host":
        return compile_and_run_on_host(c_sources)
    with open(expect, "r", encoding="utf-8") as handle:
        return handle.read()
