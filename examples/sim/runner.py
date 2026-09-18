# THE RUNNER — hand a built system to kathryn's simulator and read back what
# the run wrote. Nothing here knows what the machine is: the system carries
# the rtl, the test module and its own env, and the answer is result.json.

from __future__ import annotations

import os
import pathlib

from kathryn.sim.backend.cocotb import get_backend
from kathryn.sim.rtl import open_rtl
from kathryn.sim.runner_cocotb import CocotbSim

from examples.sim.options import SimOptions
from examples.sim.result import RESULT_FILE, RunResult, read_result
from examples.sim.system import SimSystem

REPO     = pathlib.Path(__file__).resolve().parents[2]
SIM_ROOT = REPO / "generated" / "sim"


def run_system(system: SimSystem, options: SimOptions = SimOptions()) -> RunResult:
    """Build (or reuse) the compiled simulator, run the system's test, read the result."""
    build = CocotbSim.build(open_rtl(pathlib.Path(system.rtl_dir)), get_backend(options.sim),
                            cache_root = SIM_ROOT / "sim_build",
                            waves      = options.waves,
                            log_path   = pathlib.Path(system.run_dir) / "build.log")

    # cocotb imports the test module inside the simulator, where the repo is not
    # on sys.path; the system's own env travels beside it, unread.
    env = dict(system.env)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)
    status = build.run_test(system.test_module, system.test_case,
                            extra_env = env,
                            waves     = options.waves,
                            log_path  = pathlib.Path(system.run_dir) / "sim.log")

    result_path = os.path.join(system.run_dir, RESULT_FILE)
    if not os.path.isfile(result_path):
        raise RuntimeError(
            f"the simulation wrote no {RESULT_FILE} (cocotb said {status}) — "
            f"see {os.path.join(system.run_dir, 'sim.log')}")
    return read_result(result_path)
