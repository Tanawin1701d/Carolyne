# compile_tool — C sources in, two memory images out, with no operating
# system anywhere in the picture, for any TARGET the tool describes
# (target.py: rv32i, rv32im, mips32).
#
# What it does, in order: lay out the memories — from the Carolyne machine
# when the target has one, from the sizes when it has not yet — generate the
# linker script and the C header from that layout, compile and link with the
# target's toolchain, hold every instruction to the ISA description when the
# target has one, and flatten the ELF into one image per memory.
#
# The layout is the reason this stays consistent: the linker script, the C
# header, the images and a simulation harness all read that one object, so no
# address is written down twice.
#
# Usage:
#     from examples.compile_tool import build_program
#     program = build_program(["hello.c"], target="rv32i", imem_bytes=8192, dmem_bytes=4096)
#     program.image.write_files("out/")

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Sequence

from carolyne.uarch.o3.config import CPUO3_Config

from .elf32 import Elf32, read_elf32
from .image import ProgramImage, build_image
from .layout import MemoryLayout
from .machine import (DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES, config_for_sizes,
                      idx_width_for)
from .target import MIPS32, RV32I, RV32IM, TARGETS, Target, resolve_target, target_named
from .toolchain import BuildArtifacts, compile_program
from .verify import VerifyReport, verify_program

__all__ = ["build_program", "layout_for", "Program",
           "Target", "TARGETS", "RV32I", "RV32IM", "MIPS32", "target_named",
           "MemoryLayout", "ProgramImage", "VerifyReport",
           "config_for_sizes", "idx_width_for",
           "DEFAULT_IMEM_BYTES", "DEFAULT_DMEM_BYTES"]

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "generated", "programs")
DEFAULT_LANES = 2


# --- one built program --------------------------------------------------------
@dataclass(frozen=True)
class Program:
    """Everything one build produced, so nothing has to be recomputed."""

    name    : str
    target  : Target
    config  : Optional[CPUO3_Config]     # None for a target with no Carolyne machine yet
    layout  : MemoryLayout
    elf     : Elf32
    image   : ProgramImage
    build   : BuildArtifacts
    report  : VerifyReport

    def describe(self) -> str:
        return "\n\n".join((f"target {self.target.name}",
                            self.layout.describe(),
                            self.image.describe(),
                            self.report.describe()))


# --- the layout for a target ---------------------------------------------------
def layout_for(target     : Target,
               imem_bytes : int = DEFAULT_IMEM_BYTES,
               dmem_bytes : int = DEFAULT_DMEM_BYTES,
               lanes      : int = DEFAULT_LANES,
               config     : CPUO3_Config = None) -> "tuple[Optional[CPUO3_Config], MemoryLayout]":
    """The machine config (when the target has one) and the layout it decides."""
    if config is None and target.machine_config is not None:
        config = target.machine_config(imem_bytes, dmem_bytes, lanes)
    if config is not None:
        return config, MemoryLayout.from_config(config)
    return None, MemoryLayout.from_sizes(imem_bytes, dmem_bytes, lanes, target.reset_pc)


# --- the whole flow -----------------------------------------------------------
def build_program(sources    : Sequence[str],
                  target     : "str | Target" = "rv32i",
                  imem_bytes : int = DEFAULT_IMEM_BYTES,
                  dmem_bytes : int = DEFAULT_DMEM_BYTES,
                  name       : str = "program",
                  opt        : str = "-O2",
                  out_dir    : str = None,
                  lanes      : int = DEFAULT_LANES,
                  config     : CPUO3_Config = None,
                  verify     : bool = True,
                  write_files: bool = True) -> Program:
    """Compile C sources into one image per memory.

    - `target` picks the toolchain, the runtime and the description (target.py)
    - `config` overrides the memory sizes: pass the machine you will build,
      and the images are laid out for exactly it
    - `verify=False` skips the ISA check, which is only useful when you are
      deliberately inspecting a program the machine cannot run; a target with
      no description is never verified, and its report says so
    """
    target         = resolve_target(target)
    config, layout = layout_for(target, imem_bytes, dmem_bytes, lanes, config)
    out_dir        = out_dir or os.path.join(DEFAULT_OUT, name)

    build  = compile_program(sources, layout, out_dir, target, opt=opt, name=name)
    elf    = read_elf32(build.elf_path)
    _reject_wrong_machine(elf, target)
    _reject_wrong_entry(elf, layout)
    report = (verify_program(elf, target.isa()) if target.can_verify
              else VerifyReport.not_verified(target.name))
    if verify:
        report.raise_if_bad()

    image = build_image(elf, layout)
    if write_files:
        image.write_files(out_dir)

    return Program(name=name, target=target, config=config, layout=layout, elf=elf,
                   image=image, build=build, report=report)


def _reject_wrong_machine(elf: Elf32, target: Target) -> None:
    if elf.machine != target.elf_machine:
        raise ValueError(
            f"{elf.path} is for e_machine {elf.machine}, but target {target.name} "
            f"links for {target.elf_machine} — the wrong toolchain answered")


def _reject_wrong_entry(elf: Elf32, layout: MemoryLayout) -> None:
    """The program must begin where the core begins: the ISA's reset_pc.

    The linker script puts _start there, so this holds today — it is the check
    that says so, instead of an agreement nothing looks at.
    """
    if elf.entry != layout.reset_pc:
        raise ValueError(
            f"{elf.path} starts at 0x{elf.entry:08x}, but the ISA's reset_pc "
            f"is 0x{layout.reset_pc:08x} — the core would begin fetching "
            f"somewhere this program is not")
