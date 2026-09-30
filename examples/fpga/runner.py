# THE RUNNER — a built FpgaSystem to a result, three ways: the bitstream build
# (cached by the emitted RTL's content), the run on the board, and the run of
# the SAME driver against the simulated bridge. Nothing here knows what the
# machine is: the system carries the rtl, the map and the spec.

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time
from typing import Dict, Sequence

from kathryn.sim.rtl import open_rtl

from examples.fpga.backend import Bitstream, BitstreamRequest, bitstream_key, get_backend
from examples.fpga.backend.vivado.backend import EXPORT_DIR, HOST_MAP_FILE
from examples.fpga.backend.vivado.report import SUMMARY_FILE, describe_summary, parse_build_summary
from examples.fpga.board import (RUN_SCRIPT, BoardLink, SshTransport, deploy_machine, deploy_programs,
                                 remote_spec_path)
from examples.fpga.bridge import OUT_DIR_ENV, SPEC_ENV, HostRunOutcome, read_bridge_run_spec
from examples.fpga.options import FpgaOptions
from examples.fpga.result import OUTCOME_FILE, run_result_of_outcome
from examples.fpga.system import FpgaMachine, FpgaProgram, FpgaSystem
from examples.sim.options import SimOptions
from examples.sim.result import RESULT_FILE, RunResult, read_result, write_result
from examples.sim.runner import SIM_ROOT
from examples.sim.runner import run_system as run_sim_system
from examples.sim.system import SimSystem

REPO      = pathlib.Path(__file__).resolve().parents[2]
FPGA_ROOT = REPO / "generated" / "fpga"
OK_MARKER = "ok"

BRIDGE_TEST_MODULE = "examples.o3.fpga.cocotb_test"
BRIDGE_TEST_CASE   = "run_program"

BOARD_LOG          = "board.log"
BOARD_SESSION_SLACK_S = 120.0       # over the programs' own timeouts: overlay load, uploads


# ---- the bitstream ------------------------------------------------------------------------

def build_bitstream(machine: FpgaMachine, options: FpgaOptions = FpgaOptions()) -> Bitstream:
    """The machine's bitstream, built only when the cache has no bitstream for
    this RTL + board + clock (bitstream_key); a finished build leaves an `ok` marker."""
    backend = get_backend(options.backend)
    board   = backend.board(options.board)
    rtl     = open_rtl(pathlib.Path(machine.rtl_dir))
    request = BitstreamRequest(rtl_dir    = machine.rtl_dir,
                               top_module = machine.top_module,
                               host_map   = machine.host_map,
                               board      = board,
                               clock_mhz  = options.clock_mhz,
                               jobs       = options.jobs,
                               synth_only = options.synth_only)
    key       = bitstream_key(rtl, backend, request)
    request   = dataclasses.replace(request, name=f"carolyne_{key}")
    build_dir = FPGA_ROOT / backend.name / key
    export    = build_dir / EXPORT_DIR

    if (build_dir / OK_MARKER).is_file():
        summary = export / SUMMARY_FILE
        return Bitstream(bit_path      = str(export / f"{request.name}.bit"),
                         hwh_path      = str(export / f"{request.name}.hwh"),
                         host_map_path = str(export / HOST_MAP_FILE),
                         build_dir     = str(build_dir),
                         reused        = True,
                         report        = parse_build_summary(summary) if summary.is_file() else {})

    started   = time.perf_counter()
    bitstream = backend.build(request, build_dir, log_path=build_dir / "vivado_stdout.log")
    (build_dir / OK_MARKER).write_text(f"{request.name} {time.perf_counter() - started:.0f}s\n",
                                       encoding="utf-8")
    return bitstream


def describe_bitstream(bitstream: Bitstream) -> str:
    what = "reused" if bitstream.reused else "built"
    return "\n".join([f"bitstream : {what} in {bitstream.build_dir}",
                      f"files     : {bitstream.bit_path}",
                      f"summary   : {describe_summary(bitstream.report) if bitstream.report else 'none'}"])


# ---- the board ----------------------------------------------------------------------------------

def run_many_on_board(machine   : FpgaMachine,
                      programs  : Sequence[FpgaProgram],
                      bitstream : Bitstream,
                      link      : BoardLink,
                      options   : FpgaOptions = FpgaOptions()) -> Dict[str, RunResult]:
    """Every program on the board in ONE session: one bitstream download, one
    overlay load, then run_on_board.py over all the specs.

    - the result of each lands in <run_dir>/board, apart from its sim run
    - refuses a bitstream that missed timing unless the options allow it
    """
    if bitstream.timing_met is False and not options.allow_timing_failure:
        raise RuntimeError(
            f"the bitstream in {bitstream.build_dir} missed timing — pass --allow-timing-failure "
            f"to run it anyway, or rebuild with a slower --clock-mhz")
    if not os.path.isfile(bitstream.bit_path):
        raise RuntimeError(f"no bitstream at {bitstream.bit_path} (a --synth-only build has none)")

    transport = SshTransport(link)
    remote    = deploy_machine(transport, link.remote_dir, bitstream)
    deploy_programs(transport, remote, programs)

    specs   = " ".join(shlex.quote(remote_spec_path(remote, p)) for p in programs)
    inner   = (f"{link.shell_prelude} && cd {shlex.quote(remote)} && "
               f"{link.python} {RUN_SCRIPT} {os.path.basename(bitstream.bit_path)} {specs}")
    timeout = sum(read_bridge_run_spec(p.spec_path).timeout_s for p in programs) + BOARD_SESSION_SLACK_S
    done    = transport.run(f"bash -c {shlex.quote(inner)}", timeout_s=timeout)

    results = {}
    for program in programs:
        out_dir = os.path.join(program.run_dir, "board")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, BOARD_LOG), "w", encoding="utf-8") as log:
            log.write(done.stdout)
            log.write(done.stderr)
        if done.returncode:
            continue
        outcome_path = os.path.join(out_dir, OUTCOME_FILE)
        transport.download(f"{remote}/runs/{program.name}/{OUTCOME_FILE}", outcome_path)
        with open(outcome_path, "r", encoding="utf-8") as handle:
            outcome = HostRunOutcome.from_dict(json.load(handle))
        result = run_result_of_outcome(outcome, out_dir)
        write_result(os.path.join(out_dir, RESULT_FILE), result)
        results[program.name] = result

    if done.returncode:
        raise RuntimeError(
            f"run_on_board.py exited {done.returncode} on {link.target}; the log ends:\n"
            f"{done.stdout[-2000:]}{done.stderr[-2000:]}")
    return results


def run_on_board(system: FpgaSystem, bitstream: Bitstream, link: BoardLink,
                 options: FpgaOptions = FpgaOptions()) -> RunResult:
    return run_many_on_board(system.machine, [system.program], bitstream, link, options)[system.program.name]


# ---- the plain simulator, for the comparison ------------------------------------------------------

SIM_REFERENCE_SUFFIX = "_simref"


def run_plain_simulation(program: FpgaProgram, target: str, dmem_bytes: int, lanes: int,
                         opt: str, cycle_limit: int, name: str = "") -> RunResult:
    """The same program through `python -m examples.sim run` in ITS OWN process —
    Kathryn emits once per process, and this one already emitted the bridged machine."""
    name = name or f"{program.name}{SIM_REFERENCE_SUFFIX}"
    argv = [sys.executable, "-m", "examples.sim", "run", *program.c_sources,
            "--target", target, "--dmem", str(dmem_bytes), "--lanes", str(lanes), f"--opt={opt}",
            "--max-cycles", str(cycle_limit or 8_000_000), "--no-log", "--expect", "none", "--name", name]
    done = subprocess.run(argv, cwd=REPO, env=_sim_env(), capture_output=True, text=True)
    path = SIM_ROOT / "run" / name / RESULT_FILE
    if not path.is_file():
        raise RuntimeError(f"the reference simulation wrote no result (rc {done.returncode}):\n{done.stdout[-2000:]}")
    return read_result(str(path))


def run_plain_simulations(programs: Sequence[FpgaProgram], target: str, dmem_bytes: int, lanes: int,
                          opt: str, cycle_limit: int) -> Dict[str, RunResult]:
    """Every program's reference through ONE `python -m examples.sim batch` process:
    one machine, one compiled simulator, the programs run back to back.

    - one-file programs only, the batch command's rule; results by the FPGA
      program's name
    """
    for program in programs:
        if len(program.c_sources) != 1:
            raise ValueError(f"run_plain_simulations: '{program.name}' has {len(program.c_sources)} "
                             f"sources — the sim batch takes one file per program")
    argv = [sys.executable, "-m", "examples.sim", "batch", *(p.c_sources[0] for p in programs),
            "--target", target, "--dmem", str(dmem_bytes), "--lanes", str(lanes), f"--opt={opt}",
            "--max-cycles", str(cycle_limit or 8_000_000), "--no-log", "--expect", "none",
            "--suffix", SIM_REFERENCE_SUFFIX]
    done = subprocess.run(argv, cwd=REPO, env=_sim_env(), capture_output=True, text=True)
    results = {}
    for program in programs:
        stem = pathlib.Path(program.c_sources[0]).stem
        path = SIM_ROOT / "run" / f"{stem}{SIM_REFERENCE_SUFFIX}" / RESULT_FILE
        if not path.is_file():
            raise RuntimeError(
                f"the reference simulation wrote no result for {stem} (rc {done.returncode}):\n{done.stdout[-2000:]}")
        results[program.name] = read_result(str(path))
    return results


def _sim_env() -> dict:
    return {**os.environ,
            "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)}


# ---- the board in simulation ----------------------------------------------------------------


def run_in_simulation(system: FpgaSystem, options: SimOptions = SimOptions()) -> RunResult:
    """The board's protocol against the simulated bridge: the same driver, cocotb's clock.

    - the sim's own runner does the work; the compiled simulator is cached with
      every other under generated/sim/sim_build, keyed by the emitted RTL
    - the result lands in <run_dir>/sim, apart from a board run of the same program
    """
    out_dir = os.path.join(system.program.run_dir, "sim")
    os.makedirs(out_dir, exist_ok=True)
    sim_system = SimSystem(name        = system.program.name,
                           run_dir     = out_dir,
                           rtl_dir     = system.machine.rtl_dir,
                           test_module = BRIDGE_TEST_MODULE,
                           test_case   = BRIDGE_TEST_CASE,
                           env         = {SPEC_ENV: system.program.spec_path, OUT_DIR_ENV: out_dir},
                           c_sources   = system.program.c_sources)
    return run_sim_system(sim_system, options)
