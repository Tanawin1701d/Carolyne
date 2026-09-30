# The RV32IM cocotb entry of the sim flow: the shared simulation body
# (examples/o3/sim/cocotb_run.py) over this family's own config builder.
# cocotb imports this module inside the simulator, where the repo is not on
# sys.path.

from __future__ import annotations

import pathlib
import sys

import cocotb

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from examples.o3.sim.cocotb_run import run_o3_program        # noqa: E402
from examples.o3.rv32im.config   import gen_o3_rv32im_config  # noqa: E402


@cocotb.test()
async def run_program(dut):
    """Run the program on the RV32IM machine until it stops."""
    await run_o3_program(dut, gen_o3_rv32im_config)
