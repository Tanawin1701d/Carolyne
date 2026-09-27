# The DESCRIPTION half of the O3 example for MIPS32: one ISA and one machine
# config; the machine itself is examples/o3/core/build.py, the same one the
# RV32IM config builds.
#
# Nothing here builds hardware — these are the two objects a generator is
# handed: the ISA says what the instructions are, the config how wide and how
# deep the machine running them is.

from __future__ import annotations

from typing import Dict, Tuple

from carolyne.isa.mips import Mips32
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType

from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from examples.o3.core.mem_size import idx_width_for


def mips32_isa() -> Mips32:
    """The MIPS32 description as the package ships it."""
    return Mips32()


def mips32_stations(isa         : Mips32,
                    exec_size   : int = 16,
                    ls_size     : int = 8,
                    br_size     : int = 8,
                    alu_cnt     : int = 2,
                    muldiv_size : int = 8) -> Tuple[RsvSpec, ...]:
    """Four stations: compute out of order; memory, branches and mul/div in order.

    - the compute station holds `alu_cnt` ALUs, the SAME unit listed twice
    - mem and control are in order, which their units require, and an
      in-order station feeds exactly one unit — so each takes a station
    - muldiv has its own station: only it carries the hi/lo slots
    """
    units = (isa.unit("alu"),) * alu_cnt
    return (RsvSpec(True,  exec_size,   units,                  RsvType.RSV_EXEC),
            RsvSpec(False, ls_size,     (isa.unit("mem"),),     RsvType.RSV_LD_ST),
            RsvSpec(False, br_size,     (isa.unit("control"),), RsvType.RSV_BRANCH),
            RsvSpec(False, muldiv_size, (isa.unit("muldiv"),),  RsvType.RSV_EXEC))


def gen_o3_mips32_config(fe_lanes            : int = 2,
                         commit_lanes        : int = 2,
                         phy_size            : int = 64,
                         hilo_phy_size       : int = 32,
                         exec_rsv_size       : int = 16,
                         ls_rsv_size         : int = 8,
                         br_rsv_size         : int = 8,
                         alu_cnt             : int = 2,
                         muldiv_rsv_size     : int = 8,
                         rob_depth           : int = 32,
                         sptag_len           : int = 5,
                         st_buf_depth        : int = 32,
                         instr_mem_idx_width : int = 10,
                         data_mem_idx_width  : int = 10) -> CPUO3_Config:
    """One O3 machine over MIPS32. Every knob is named, none is derived here.

    - hi and lo are one-register classes, and EVERY in-flight branch holds one
      physical register of each until it retires (the engine allocates a
      branch every destination class), so their files are sized for the
      instructions in flight, not for the class
    """
    isa = mips32_isa()
    return CPUO3_Config(isa                 = isa,
                        fe_lanes            = fe_lanes,
                        commit_lanes        = commit_lanes,
                        phy_specs           = ((isa.reg_file("r"),  phy_size),
                                               (isa.reg_file("hi"), hilo_phy_size),
                                               (isa.reg_file("lo"), hilo_phy_size)),
                        rsv_specs           = mips32_stations(isa, exec_rsv_size,
                                                              ls_rsv_size, br_rsv_size,
                                                              alu_cnt, muldiv_rsv_size),
                        rob_depth           = rob_depth,
                        sptag_len           = sptag_len,
                        st_buf_depth        = st_buf_depth,
                        instr_mem_idx_width = instr_mem_idx_width,
                        data_mem_idx_width  = data_mem_idx_width)


def gen_o3_mips32_config_for_sizes(imem_bytes : int = DEFAULT_IMEM_BYTES,
                                   dmem_bytes : int = DEFAULT_DMEM_BYTES,
                                   **knobs) -> Tuple[CPUO3_Config, Dict[str, int]]:
    """This machine with memories of the requested size, and the knobs that rebuild it.

    - the knobs ARE what gen_o3_mips32_config was called with, so another
      process builds the same machine from them and re-derives no width
    """
    isa    = mips32_isa()
    lanes  = knobs.get("fe_lanes", 2)
    kwargs = dict(knobs,
                  instr_mem_idx_width = idx_width_for(imem_bytes, lanes, isa.ilen_bytes),
                  data_mem_idx_width  = idx_width_for(dmem_bytes, 1, isa.dlen_bytes))
    return gen_o3_mips32_config(**kwargs), kwargs
