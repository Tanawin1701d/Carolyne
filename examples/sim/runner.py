# THE RUNNER — hand a built machine and its programs to kathryn's simulator and
# read back what each run wrote. Nothing here knows what the machine is: the
# batch carries the rtl, the test module and each program's own env, and the
# answers are the programs' result.json files.
#
# The compiled simulator is cached by the emitted RTL's content, so a batch on
# a machine that was compiled before starts at once; a new machine compiles
# once and then serves every program.

from __future__ import annotations

import os
import pathlib
from typing import Dict

from kathryn.sim.backend.cocotb import get_backend
from kathryn.sim.rtl import open_rtl
from kathryn.sim.runner_cocotb import CocotbSim

from examples.sim.options import SimOptions
from examples.sim.result import RESULT_FILE, RunResult, read_result
from examples.sim.system import BATCH_ENV, BATCH_FILE, SimBatch, SimSystem, write_sim_batch

REPO     = pathlib.Path(__file__).resolve().parents[2]
SIM_ROOT = REPO / "generated" / "sim"


def run_batch(batch: SimBatch, options: SimOptions = SimOptions()) -> Dict[str, RunResult]:
    """Build (or reuse) the compiled simulator, run every program of the batch in
    ONE simulator process, read each result back — by program name."""
    machine_dir = pathlib.Path(batch.machine.rtl_dir).parent
    build = CocotbSim.build(open_rtl(pathlib.Path(batch.machine.rtl_dir)), get_backend(options.sim),
                            cache_root = SIM_ROOT / "sim_build",
                            waves      = options.waves,
                            log_path   = machine_dir / "build.log")

    batch_path = machine_dir / BATCH_FILE
    write_sim_batch(str(batch_path), batch)

    # cocotb imports the test module inside the simulator, where the repo is not
    # on sys.path; the batch file carries every program's own env, unread here.
    env = {BATCH_ENV: str(batch_path),
           "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)}
    status = build.run_test(batch.machine.test_module, batch.machine.test_case,
                            extra_env = env,
                            waves     = options.waves,
                            log_path  = machine_dir / "sim.log")

    results, missing = {}, []
    for program in batch.programs:
        path = os.path.join(program.run_dir, RESULT_FILE)
        if os.path.isfile(path):
            results[program.name] = read_result(path)
        else:
            missing.append(program.name)
    if missing:
        raise RuntimeError(
            f"the simulation wrote no {RESULT_FILE} for {', '.join(missing)} (cocotb said "
            f"{status}) — see {machine_dir / 'sim.log'}")
    return results


def run_system(system: SimSystem, options: SimOptions = SimOptions()) -> RunResult:
    """One program on its machine: a batch of one."""
    return run_batch(system.as_batch(), options)[system.name]
