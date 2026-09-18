# The DESCRIPTION half of the O3 example for RV32IM: one ISA and one machine
# config; the machine itself is examples/o3/core/build.py.
#
# Nothing here builds hardware — these are the two objects a generator is
# handed, and they are separate because they answer different questions: the
# ISA says what the instructions are, the config says how wide and how deep
# the machine running them is.
#
# The ISA comes as it ships: every RV32I unit now carries its own semantics,
# (system/fence/ecall/ebreak are out until a trap policy), so this file states no
# hardware of its own.

from __future__ import annotations

from typing import Dict, Tuple

from carolyne.isa.riscv.rv32im import Rv32im
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType

from examples.compile_tool.layout import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from examples.o3.core.mem_size import idx_width_for


def rv32im_isa() -> Rv32im:
    """The RISC-V description as the package ships it: RV32IM."""
    return Rv32im()


def rv32im_stations(isa         : Rv32im,
                   exec_size   : int = 16,
                   ls_size     : int = 8,
                   br_size     : int = 8,
                   alu_cnt     : int = 2,
                   muldiv_size : int = 8) -> Tuple[RsvSpec, ...]:
    """Four stations: compute out of order; memory, branches and mul/div in order.

    - the compute station holds `alu_cnt` ALUs, the SAME unit listed twice:
      how many a machine has is the machine's choice, not the ISA's, and each
      copy gets its own issue path
    - NOT here: a `system` unit. fence/ecall/ebreak are out of the
      description until a trap policy exists (riscv/uop.py)
    - mem and control are in order, which their units require, and an
      in-order station feeds exactly one unit — so each takes a station
    """
    units = (isa.unit("alu"),) * alu_cnt
    return (RsvSpec(True,  exec_size,   units,                 RsvType.RSV_EXEC),
            RsvSpec(False, ls_size,     (isa.unit("mem"),),    RsvType.RSV_LD_ST),
            RsvSpec(False, br_size,     (isa.unit("control"),),RsvType.RSV_BRANCH),
            RsvSpec(False, muldiv_size, (isa.unit("muldiv"),), RsvType.RSV_EXEC))


def gen_o3_rv32im_config(fe_lanes            : int = 2,
                        commit_lanes        : int = 2,
                        phy_size            : int = 64,
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
    """One O3 machine over RV32IM. Every knob is named, none is derived here."""
    isa = rv32im_isa()
    return CPUO3_Config(isa                 = isa,
                        fe_lanes            = fe_lanes,
                        commit_lanes        = commit_lanes,
                        phy_specs           = ((isa.reg_file("x"), phy_size),),
                        rsv_specs           = rv32im_stations(isa, exec_rsv_size,
                                                             ls_rsv_size, br_rsv_size,
                                                             alu_cnt, muldiv_rsv_size),
                        rob_depth           = rob_depth,
                        sptag_len           = sptag_len,
                        st_buf_depth        = st_buf_depth,
                        instr_mem_idx_width = instr_mem_idx_width,
                        data_mem_idx_width  = data_mem_idx_width)


def gen_o3_rv32im_config_for_sizes(imem_bytes : int = DEFAULT_IMEM_BYTES,
                                   dmem_bytes : int = DEFAULT_DMEM_BYTES,
                                   **knobs) -> Tuple[CPUO3_Config, Dict[str, int]]:
    """This machine with memories of the requested size, and the knobs that rebuild it.

    - the knobs ARE what gen_o3_rv32im_config was called with, so another process builds
      the same machine from them and re-derives no width of its own
    - the instruction memory has one bank per front-end lane, so its index width
      falls as fe_lanes rises for the same total size
    """
    isa    = rv32im_isa()
    lanes  = knobs.get("fe_lanes", 2)
    kwargs = dict(knobs,
                  instr_mem_idx_width = idx_width_for(imem_bytes, lanes, isa.ilen_bytes),
                  data_mem_idx_width  = idx_width_for(dmem_bytes, 1, isa.dlen_bytes))
    return gen_o3_rv32im_config(**kwargs), kwargs
