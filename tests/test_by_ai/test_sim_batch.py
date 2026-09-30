# One machine, many programs: the batch the sim hands one simulator process,
# how the cocotb side reads every program's spec out of it, and the
# machine-side builder that lays a program out for an already-emitted machine.

from __future__ import annotations

import json
import shutil

import pytest

from examples.o3.sim.run_spec import SPEC_ENV, SPEC_FILE, read_run_spec, read_run_specs, write_run_spec
from examples.o3.sim.system import build_o3_sim_program, machine_label
from examples.o3.rv32im.config import TARGET, gen_o3_rv32im_config_for_sizes
from examples.o3.rv32im.sim import TEST_CASE, TEST_MODULE
from examples.sim.cli import build_parser
from examples.sim.system import (BATCH_ENV, SimBatch, SimMachine, SimProgram, SimSystem, read_sim_batch,
                                 write_sim_batch)
from examples.sim.sweep import SweepRow, render
from tests.test_by_ai.test_rv32im_system import a_spec


def a_machine(tmp_path) -> SimMachine:
    config, knobs = gen_o3_rv32im_config_for_sizes(8192, 16384, fe_lanes=2)
    return SimMachine(label=machine_label(TARGET, 2, 8192, 16384), target=TARGET,
                      rtl_dir=str(tmp_path / "rtl"), test_module=TEST_MODULE, test_case=TEST_CASE,
                      config_knobs=dict(knobs), config=config)


# ---- the batch file ------------------------------------------------------------------

def test_a_batch_names_every_program_and_its_own_env(tmp_path):
    machine  = a_machine(tmp_path)
    programs = tuple(SimProgram(f"p{i}", str(tmp_path / f"p{i}"), {SPEC_ENV: f"/x/p{i}/{SPEC_FILE}"}, (f"p{i}.c",))
                     for i in range(3))
    path = tmp_path / "sim_batch.json"
    write_sim_batch(str(path), SimBatch(machine, programs))
    entries = read_sim_batch(str(path))
    assert [e["name"] for e in entries] == ["p0", "p1", "p2"]
    assert entries[1]["env"] == {SPEC_ENV: f"/x/p1/{SPEC_FILE}"} and entries[1]["run_dir"].endswith("p1")
    assert json.loads(path.read_text())["machine"] == machine.label


def test_without_a_batch_the_test_runs_the_one_spec_its_env_names(tmp_path, monkeypatch):
    spec_path = tmp_path / SPEC_FILE
    write_run_spec(str(spec_path), a_spec(name="alone"))
    monkeypatch.delenv(BATCH_ENV, raising=False)
    monkeypatch.setenv(SPEC_ENV, str(spec_path))
    assert read_sim_batch() is None
    assert [s.name for s in read_run_specs()] == ["alone"]


def test_a_batch_reads_every_programs_spec_in_order(tmp_path, monkeypatch):
    programs = []
    for name in ("hello", "fib", "hanoi"):
        spec_path = tmp_path / name / SPEC_FILE
        write_run_spec(str(spec_path), a_spec(name=name, out_dir=str(tmp_path / name)))
        programs.append(SimProgram(name, str(tmp_path / name), {SPEC_ENV: str(spec_path)}, (f"{name}.c",)))
    batch_path = tmp_path / "sim_batch.json"
    write_sim_batch(str(batch_path), SimBatch(a_machine(tmp_path), tuple(programs)))
    monkeypatch.setenv(BATCH_ENV, str(batch_path))
    monkeypatch.delenv(SPEC_ENV, raising=False)           # the batch is enough on its own
    assert [s.name for s in read_run_specs()] == ["hello", "fib", "hanoi"]


def test_a_batch_program_without_a_spec_is_refused(tmp_path, monkeypatch):
    batch_path = tmp_path / "sim_batch.json"
    write_sim_batch(str(batch_path), SimBatch(a_machine(tmp_path), (SimProgram("bare", str(tmp_path), {}, ()),)))
    monkeypatch.setenv(BATCH_ENV, str(batch_path))
    with pytest.raises(RuntimeError, match="names no"):
        read_run_specs()


def test_the_bridge_test_reads_its_programs_out_of_the_batch_too(tmp_path, monkeypatch):
    # the sim exports ONLY the batch file, so a test that reads the bare
    # environment sees no spec; the bridge test must take each program's env
    # from the batch the way read_run_specs does
    from examples.fpga.bridge import OUT_DIR_ENV, SPEC_ENV as BRIDGE_SPEC_ENV
    from examples.o3.fpga.cocotb_test import program_envs

    programs = tuple(SimProgram(f"p{i}", str(tmp_path / f"p{i}"),
                                {BRIDGE_SPEC_ENV: f"/x/p{i}/spec.json", OUT_DIR_ENV: f"/x/p{i}/sim"}, ())
                     for i in range(2))
    batch_path = tmp_path / "sim_batch.json"
    write_sim_batch(str(batch_path), SimBatch(a_machine(tmp_path), programs))
    monkeypatch.setenv(BATCH_ENV, str(batch_path))
    monkeypatch.delenv(BRIDGE_SPEC_ENV, raising=False)
    assert [env[BRIDGE_SPEC_ENV] for env in program_envs()] == ["/x/p0/spec.json", "/x/p1/spec.json"]

    monkeypatch.delenv(BATCH_ENV)                          # no batch: the process env is the one program
    monkeypatch.setenv(BRIDGE_SPEC_ENV, "/y/spec.json")
    assert [env[BRIDGE_SPEC_ENV] for env in program_envs()] == ["/y/spec.json"]

    write_sim_batch(str(batch_path), SimBatch(a_machine(tmp_path), (SimProgram("bare", str(tmp_path), {}, ()),)))
    monkeypatch.setenv(BATCH_ENV, str(batch_path))
    with pytest.raises(RuntimeError, match="names no"):
        program_envs()


def test_a_system_is_a_batch_of_one():
    system = SimSystem("hello", "/r/hello", "/m/rtl", "mod", "case", {SPEC_ENV: "/r/hello/spec"}, ("hello.c",))
    batch  = system.as_batch()
    assert batch.machine.rtl_dir == "/m/rtl" and batch.machine.test_module == "mod"
    assert len(batch.programs) == 1 and batch.programs[0].env == {SPEC_ENV: "/r/hello/spec"}


# ---- the machine-side program builder ------------------------------------------------------

@pytest.mark.skipif(shutil.which("riscv64-unknown-elf-gcc") is None, reason="needs the riscv toolchain")
def test_a_program_is_laid_out_for_an_already_emitted_machine(tmp_path):
    # no emit here: the builder takes the machine's config and writes the
    # program's images and spec into ITS run dir, beside nothing of the machine's
    machine = a_machine(tmp_path)
    program = build_o3_sim_program(machine, ["examples/compile_tool/programs/hello.c"],
                                   str(tmp_path / "run" / "hello"), "hello", log_enabled=False)
    assert program.name == "hello" and program.c_sources == ("examples/compile_tool/programs/hello.c",)
    spec = read_run_spec(program.env[SPEC_ENV])
    assert spec.config_kwargs == machine.config_knobs
    assert spec.out_dir == program.run_dir and not spec.log_enabled
    assert all(p.startswith(str(tmp_path / "run" / "hello" / "program")) for p in spec.instr_hex)


def test_a_machine_built_elsewhere_cannot_lay_a_program_out():
    stranger = SimMachine("x", TARGET, "/rtl", TEST_MODULE, TEST_CASE)     # no config: another process's
    with pytest.raises(ValueError, match="carries no config"):
        build_o3_sim_program(stranger, ["a.c"], "/r", "a")


# ---- the command line and the table ---------------------------------------------------------

def test_the_batch_command_names_runs_by_stem_and_suffix():
    parser = build_parser()
    batch  = parser.parse_args(["batch", "a.c", "b.c", "--dmem", "16K", "--suffix", "_ref", "--no-log"])
    assert batch.command == "batch" and batch.c_sources == ["a.c", "b.c"]
    assert batch.suffix == "_ref" and batch.dmem == 16384 and not batch.log
    run = parser.parse_args(["run", "a.c", "b.c", "--name", "two_files"])
    assert run.c_sources == ["a.c", "b.c"] and run.name == "two_files"      # several files, ONE program


def test_the_sweep_table_counts_matches_and_names_one_process():
    rows = [SweepRow("hello", "rv32im", "-O2", "exit", 244, 0, True),
            SweepRow("fib",   "rv32im", "-O2", "exit", 3151, 0, False),
            SweepRow("hang",  "rv32im", "-O2", "idle", 2000, -1, True)]
    table = render(rows, 12.5)
    assert "1/3 matched in 12.5s, one simulator process" in table
    assert rows[0].matched and not rows[1].matched and not rows[2].matched
