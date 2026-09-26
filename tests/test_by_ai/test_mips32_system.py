# The mips32 system: the shared O3 recipe bound to the MIPS32 family, and
# what the sim's registry knows about it. Nothing here starts a simulator.

from __future__ import annotations

from importlib import import_module

from examples.compile_tool import MemoryLayout, target_named
from examples.o3.mips32.config import gen_o3_mips32_config, gen_o3_mips32_config_for_sizes
from examples.o3.mips32.system import TARGET, TEST_CASE, TEST_MODULE
from examples.o3.core.mem_size import machine_mem_of
from examples.sim.cli import SYSTEMS


def test_the_spec_rebuilds_the_very_machine_the_system_emitted():
    config, knobs = gen_o3_mips32_config_for_sizes(8192, 16384, fe_lanes=2)
    assert gen_o3_mips32_config(**knobs) == config


def test_the_cocotb_test_the_system_names_exists():
    assert TARGET == "mips32"
    assert hasattr(import_module(TEST_MODULE), TEST_CASE)


def test_the_family_files_are_thin_bindings_over_the_shared_recipe():
    # a family names its builder, its target and its test; the recipe is one,
    # and the simulator-side entry imports no toolchain
    system = open("examples/o3/mips32/system.py",      encoding="utf-8").read()
    cocotb = open("examples/o3/mips32/cocotb_test.py", encoding="utf-8").read()
    assert "build_o3_system(" in system and "build_model(" not in system
    assert "run_o3_program(" in cocotb and "build_model(" not in cocotb
    assert "compile_tool" not in cocotb


def test_the_sim_registry_names_both_families():
    assert sorted(SYSTEMS) == ["mips32", "rv32im"]


def test_the_images_are_laid_out_where_the_machine_fetches():
    # the code region starts at the ISA's reset vector, and the data region
    # keeps the doors clear of it
    config = gen_o3_mips32_config(fe_lanes=2)
    layout = MemoryLayout.from_spec(machine_mem_of(config))
    assert layout.imem_base == config.reset_pc == 0xBFC00000
    assert layout.imem_banks == 2 and layout.word_bytes == 4
    assert layout.imem_idx_width == config.instr_mem_spec().index_width
    assert target_named("mips32").name == "mips32"
