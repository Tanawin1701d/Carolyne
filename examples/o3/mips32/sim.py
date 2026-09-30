# The MIPS32 side of the sim flow (examples/sim): the shared O3 sim recipe
# (examples/o3/sim/system.py) bound to this family's config builder, its
# compile_tool target and its cocotb entry (sim_cocotb_test.py).

from __future__ import annotations

from examples.o3.mips32.config import TARGET, gen_o3_mips32_config_for_sizes
from examples.o3.sim.system    import build_o3_sim_machine
from examples.sim.system       import SimMachine

TEST_MODULE = "examples.o3.mips32.sim_cocotb_test"
TEST_CASE   = "run_program"


def build_sim_machine(**sizes) -> SimMachine:
    """The MIPS32 machine, emitted once for the sim to run any number of programs on."""
    return build_o3_sim_machine(gen_o3_mips32_config_for_sizes, TARGET, TEST_MODULE, TEST_CASE, **sizes)
