# The rv32im system: what its builder hands its own cocotb test, and what
# that handoff refuses. Nothing here starts a simulator.

from __future__ import annotations

from importlib import import_module

import pytest

from carolyne.debug.log import MmioDoors
from examples.compile_tool import MemoryLayout, target_named
from examples.compile_tool.image import BankImage
from examples.o3.rv32im.config import gen_o3_rv32im_config, gen_o3_rv32im_config_for_sizes
from examples.o3.rv32im.run_spec import SPEC_ENV, RunSpec, read_hex_words, read_run_spec, write_run_spec
from examples.o3.rv32im.system import TEST_CASE, TEST_MODULE


def a_spec(**over) -> RunSpec:
    fields = dict(name="hello", target="rv32im",
                  config_kwargs={"instr_mem_idx_width": 10, "data_mem_idx_width": 10,
                                 "fe_lanes": 2},
                  instr_hex=["a.hex", "b.hex"], data_hex="d.hex",
                  doors={"putchar": 1020, "putint": 1021, "exit": 1022},
                  word_bytes=4, pc_step=4, out_dir="/tmp/run")
    fields.update(over)
    return RunSpec(**fields)


# ---- the spec ---------------------------------------------------------------------

def test_a_spec_survives_the_trip_to_the_other_process(tmp_path):
    path = tmp_path / "run_spec.json"
    write_run_spec(str(path), a_spec())
    assert read_run_spec(str(path)) == a_spec()


def test_the_spec_is_found_through_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "run_spec.json"
    write_run_spec(str(path), a_spec())
    monkeypatch.setenv(SPEC_ENV, str(path))
    assert read_run_spec().name == "hello"
    monkeypatch.delenv(SPEC_ENV)
    with pytest.raises(RuntimeError, match="no run spec"):
        read_run_spec()


def test_the_spec_rebuilds_the_very_machine_the_system_emitted():
    """A CPUO3_Config cannot be serialised, so the spec carries the knobs instead."""
    config, knobs = gen_o3_rv32im_config_for_sizes(8192, 4096, fe_lanes=2)
    assert gen_o3_rv32im_config(**knobs) == config


def test_the_cocotb_test_the_system_names_exists():
    """TEST_MODULE/TEST_CASE are strings the sim forwards — this is the check."""
    assert hasattr(import_module(TEST_MODULE), TEST_CASE)


def test_both_processes_build_the_model_through_one_recipe():
    """The emitting process and the simulator process must not each spell the build.

    - a drift between two copies makes KSim resolve the manifest against names
      the compiled simulator does not have, and it fails only at run time
    """
    for path in ("examples/o3/rv32im/system.py", "examples/o3/rv32im/cocotb_test.py"):
        source = open(path, encoding="utf-8").read()
        assert "build_debug_model" in source
        assert "build_model(" not in source, f"{path} spells the build itself"


def test_the_shared_recipe_drags_no_toolchain_into_the_simulator():
    """build.py is the home BECAUSE it names no compile_tool: the simulator
    process has no cross-compiler and must not import one."""
    source = open("examples/o3/core/build.py", encoding="utf-8").read()
    assert "compile_tool" not in source


def test_the_cocotb_test_needs_nothing_from_the_compile_tool():
    """cocotb_test rebuilds the machine from the spec, not from a target table."""
    source = open("examples/o3/rv32im/cocotb_test.py", encoding="utf-8").read()
    assert "compile_tool" not in source


def test_an_image_reads_back_the_words_it_was_written_with(tmp_path):
    bank = BankImage("imem_bank0", (0x00000093, 0xdeadbeef, 0), 4)
    path = tmp_path / "imem_bank0.hex"
    path.write_text(bank.to_hex())
    assert read_hex_words(str(path)) == [0x93, 0xdeadbeef, 0]


def test_the_doors_are_the_layouts_own_word_indices():
    layout = MemoryLayout.from_spec(target_named("rv32im").machine_mem())
    doors = MmioDoors.from_layout(layout)
    assert doors.putchar == layout.data_index(layout.mmio_addrs["putchar"])
    assert doors.exit    == layout.data_index(layout.mmio_addrs["exit"])
    assert doors.putchar + 2 == doors.exit          # one word each, in order
