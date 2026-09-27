# The MIPS32 system: the shared O3 recipe (examples/o3/core/system.py) bound
# to this family's config builder, its compile_tool target and its cocotb test.

from __future__ import annotations

from typing import Sequence

from examples.o3.core.system import build_o3_system
from examples.o3.mips32.config import gen_o3_mips32_config_for_sizes
from examples.sim.system import SimSystem

TARGET      = "mips32"
TEST_MODULE = "examples.o3.mips32.cocotb_test"
TEST_CASE   = "run_program"


def build_system(c_sources: Sequence[str], run_dir: str, name: str, **options) -> SimSystem:
    """Compile, emit and write the handoff for a program on the MIPS32 machine."""
    return build_o3_system(gen_o3_mips32_config_for_sizes, TARGET, TEST_MODULE, TEST_CASE,
                           c_sources, run_dir, name, **options)
