# The MIPS32 side of the FPGA flow (examples/fpga): the shared O3 FPGA recipe
# (examples/o3/fpga/system.py) bound to this family's config builder and target.

from __future__ import annotations

from examples.fpga.system       import FpgaMachine
from examples.o3.fpga.system    import build_o3_fpga_machine
from examples.o3.mips32.config  import TARGET, gen_o3_mips32_config_for_sizes


def build_fpga_machine(**sizes) -> FpgaMachine:
    """The MIPS32 machine with its HostBridge, emitted for the FPGA flow."""
    return build_o3_fpga_machine(gen_o3_mips32_config_for_sizes, TARGET, **sizes)
