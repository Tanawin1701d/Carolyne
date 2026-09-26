# The MIPS32 machine config: the same O3 machine the RV32IM config builds,
# over a description with three register classes — two of them one-register.
# The whole-machine build is what exercises the one-register rename path.

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from kathryn import build_model, emit_verilog, reset

from carolyne.isa.mips import uop as U
from examples.o3.core.build import build_machine
from examples.o3.mips32.config import (gen_o3_mips32_config, gen_o3_mips32_config_for_sizes,
                                       mips32_isa)


def test_the_config_builds_and_sizes_every_renamed_class():
    config = gen_o3_mips32_config(fe_lanes=2, commit_lanes=2)
    isa    = config.isa
    assert config.phy_size(isa.reg_file("r")) == 64
    assert config.phy_size(isa.reg_file("hi")) == config.phy_size(isa.reg_file("lo")) == 32
    assert config.phy_idx_width(isa.reg_file("hi")) == 5
    assert config.uop_idx_width == 6                      # 63 µops
    assert config.reset_pc == 0xBFC00000


def test_the_stations_route_every_kind():
    config = gen_o3_mips32_config()
    isa    = config.isa
    assert [spec.rsv_type.name for spec in config.rsv_specs] == [
        "RSV_EXEC", "RSV_LD_ST", "RSV_BRANCH", "RSV_EXEC"]
    assert config.rsv_ids_for(U.UOP_MULT) == config.rsv_ids_for(U.UOP_MFHI) == (3,)
    assert config.rsv_ids_for(U.UOP_BEQ)  == config.rsv_ids_for(U.UOP_JR)   == (2,)
    assert config.rsv_ids_for(U.UOP_SW)   == (1,)
    assert config.rsv_ids_for(U.UOP_ADDU) == (0,)
    assert len(config.rsv_specs[0].exec_unit) == 2       # two ALUs, one unit
    assert isa.unit("muldiv").covers(isa.unit("muldiv").src_operands[2])


def test_the_sized_config_rebuilds_from_its_own_knobs():
    config, knobs = gen_o3_mips32_config_for_sizes(8192, 16384, fe_lanes=2)
    assert gen_o3_mips32_config(**knobs) == config
    assert knobs["instr_mem_idx_width"] == 10 and knobs["data_mem_idx_width"] == 12


def test_the_whole_machine_elaborates_with_its_probes():
    # The first machine with two one-register renamed classes: rename,
    # dispatch, the ROB's retire and every station must size an index of
    # width 0 without asking Kathryn for a 0-bit field.
    reset()
    machine = build_model(build_machine(gen_o3_mips32_config(fe_lanes=2, commit_lanes=2)),
                          debug=True)
    assert set(machine.core.dbg_reg_arch) == {"r", "hi", "lo"}
    assert len(machine.core.issue_lanes) == 4


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="no iverilog on PATH")
def test_the_emitted_verilog_compiles(tmp_path):
    reset()
    build_model(build_machine(gen_o3_mips32_config(fe_lanes=2, commit_lanes=2)), debug=True)
    emit_verilog(str(tmp_path), "top")
    sources = sorted(str(p) for p in tmp_path.glob("*.v"))
    done = subprocess.run(["iverilog", "-g2012", "-o", os.devnull, *sources],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-3000:]
