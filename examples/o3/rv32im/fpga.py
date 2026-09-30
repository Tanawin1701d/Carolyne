# The RV32IM side of the FPGA flow (examples/fpga): the shared O3 FPGA recipe
# (examples/o3/fpga/system.py) bound to this family's config builder and target.

from __future__ import annotations

from examples.fpga.system       import FpgaMachine
from examples.o3.fpga.system    import build_o3_fpga_machine
from examples.o3.rv32im.config  import TARGET, gen_o3_rv32im_config_for_sizes


def build_fpga_machine(**sizes) -> FpgaMachine:
    """The RV32IM machine with its HostBridge, emitted for the FPGA flow."""
    return build_o3_fpga_machine(gen_o3_rv32im_config_for_sizes, TARGET, **sizes)
