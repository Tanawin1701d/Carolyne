# The DESCRIPTION half of the RV32I example: one ISA and one machine config.
#
# Nothing here builds hardware — these are the two objects a generator is
# handed, and they are separate because they answer different questions: the
# ISA says what the instructions are, the config says how wide and how deep
# the machine running them is.
#
# The ISA comes as it ships: every RV32I unit now carries its own semantics,
# system included (isa/riscv/exec_unit_system.py), so this file states no
# hardware of its own.

from __future__ import annotations

from typing import Tuple

from carolyne.isa.riscv.rv32i import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType


def rv32i_isa() -> Rv32i:
    """RV32I as the package ships it."""
    return Rv32i()


def rv32i_stations(isa       : Rv32i,
                   exec_size : int = 16,
                   ls_size   : int = 8,
                   br_size   : int = 8,
                   alu_cnt   : int = 2) -> Tuple[RsvSpec, ...]:
    """Three stations: compute out of order, memory and branches in order.

    - the compute station holds `alu_cnt` ALUs, the SAME unit listed twice:
      how many a machine has is the machine's choice, not the ISA's, and each
      copy gets its own issue path
    - it also carries `system`, which has NO station of its own. RV32I's
      instructions use fence/ecall/ebreak, so some station must be able to
      issue them or the config refuses them as stranded; sharing costs one
      µop-id range test per unit at issue rather than a whole station
    - mem and control are in order, which their units require, and an
      in-order station feeds exactly one unit — so each takes a station
    """
    units = (isa.unit("alu"),) * alu_cnt + (isa.unit("system"),)
    return (RsvSpec(True,  exec_size, units,                 RsvType.RSV_EXEC),
            RsvSpec(False, ls_size,   (isa.unit("mem"),),    RsvType.RSV_LD_ST),
            RsvSpec(False, br_size,   (isa.unit("control"),),RsvType.RSV_BRANCH))


def rv32i_config(fe_lanes            : int = 2,
                 commit_lanes        : int = 2,
                 phy_size            : int = 64,
                 exec_rsv_size       : int = 16,
                 ls_rsv_size         : int = 8,
                 br_rsv_size         : int = 8,
                 alu_cnt             : int = 2,
                 rob_depth           : int = 32,
                 sptag_len           : int = 5,
                 st_buf_depth        : int = 32,
                 instr_mem_idx_width : int = 10,
                 data_mem_idx_width  : int = 10) -> CPUO3_Config:
    """One O3 machine over RV32I. Every knob is named, none is derived here."""
    isa = rv32i_isa()
    return CPUO3_Config(isa                 = isa,
                        fe_lanes            = fe_lanes,
                        commit_lanes        = commit_lanes,
                        phy_specs           = ((isa.reg_file("x"), phy_size),),
                        rsv_specs           = rv32i_stations(isa, exec_rsv_size,
                                                             ls_rsv_size, br_rsv_size,
                                                             alu_cnt),
                        rob_depth           = rob_depth,
                        sptag_len           = sptag_len,
                        st_buf_depth        = st_buf_depth,
                        instr_mem_idx_width = instr_mem_idx_width,
                        data_mem_idx_width  = data_mem_idx_width)
