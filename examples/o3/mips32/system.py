# The MIPS32 system: the shared O3 recipe (examples/o3/core/system.py) bound
# to this family's config builder, its compile_tool target and its cocotb test.

from __future__ import annotations

from typing import Sequence

from examples.fpga.system import FpgaMachine
from examples.o3.core.fpga_system import build_o3_fpga_machine
from examples.o3.core.system import build_o3_sim_machine, build_o3_system
from examples.o3.mips32.config import gen_o3_mips32_config_for_sizes
from examples.sim.system import SimMachine, SimSystem

TARGET      = "mips32"
TEST_MODULE = "examples.o3.mips32.cocotb_test"
TEST_CASE   = "run_program"


def build_system(c_sources: Sequence[str], run_dir: str, name: str, **options) -> SimSystem:
    """Compile, emit and write the handoff for a program on the MIPS32 machine."""
    return build_o3_system(gen_o3_mips32_config_for_sizes, TARGET, TEST_MODULE, TEST_CASE,
                           c_sources, run_dir, name, **options)


def build_fpga_machine(**sizes) -> FpgaMachine:
    """The MIPS32 machine with its HostBridge, emitted for the FPGA flow."""
    return build_o3_fpga_machine(gen_o3_mips32_config_for_sizes, TARGET, **sizes)


def build_sim_machine(**sizes) -> SimMachine:
    """The MIPS32 machine, emitted once for the sim to run any number of programs on."""
    return build_o3_sim_machine(gen_o3_mips32_config_for_sizes, TARGET, TEST_MODULE, TEST_CASE, **sizes)
