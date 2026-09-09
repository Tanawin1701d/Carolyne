# compile_tool — C sources in, two memory images out, with no operating
# system anywhere in the picture.
#
# What it does, in order: size a machine, derive the memory layout from it,
# generate the linker script and the C header from that layout, compile and
# link, hold every instruction to the ISA description, and flatten the ELF
# into one image per memory.
#
# The layout is the reason this stays consistent: it is derived from the
# CPUO3_Config the hardware is built from, and the linker script, the C
# header, the images and the simulation harness all read that one object, so
# no address is written down twice.
#
# Usage:
#     from examples.o3_riscv32.compile_tool import build_program
#     program = build_program(["hello.c"], imem_bytes=8192, dmem_bytes=4096)
#     program.image.write_files("out/")

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from carolyne.uarch.o3.config import CPUO3_Config

from .elf32 import Elf32, read_elf32
from .image import ProgramImage, build_image
from .layout import MemoryLayout
from .machine import (DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES, config_for_sizes,
                      idx_width_for)
from .toolchain import BuildArtifacts, compile_program
from .verify import VerifyReport, verify_program

__all__ = ["build_program", "Program",
           "MemoryLayout", "ProgramImage", "VerifyReport",
           "config_for_sizes", "idx_width_for",
           "DEFAULT_IMEM_BYTES", "DEFAULT_DMEM_BYTES"]

REPO_ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                           "..", "..", ".."))
DEFAULT_OUT = os.path.join(REPO_ROOT, "generated", "programs")


# --- one built program --------------------------------------------------------
@dataclass(frozen=True)
class Program:
    """Everything one build produced, so nothing has to be recomputed."""

    name    : str
    config  : CPUO3_Config
    layout  : MemoryLayout
    elf     : Elf32
    image   : ProgramImage
    build   : BuildArtifacts
    report  : VerifyReport

    def describe(self) -> str:
        return "\n\n".join((self.layout.describe(),
                            self.image.describe(),
                            self.report.describe()))


# --- the whole flow -----------------------------------------------------------
def build_program(sources    : Sequence[str],
                  imem_bytes : int = DEFAULT_IMEM_BYTES,
                  dmem_bytes : int = DEFAULT_DMEM_BYTES,
                  name       : str = "program",
                  march      : str = "rv32i",
                  opt        : str = "-O2",
                  out_dir    : str = None,
                  config     : CPUO3_Config = None,
                  verify     : bool = True,
                  write_files: bool = True) -> Program:
    """Compile C sources into one image per memory.

    - `config` overrides the memory sizes: pass the machine you will build,
      and the images are laid out for exactly it
    - `march` selects the multilib; rv32im is accepted and will fail
      verification until the ISA description grows multiply µops
    - `verify=False` skips the ISA check, which is only useful when you are
      deliberately inspecting a program the machine cannot run
    """
    config  = config or config_for_sizes(imem_bytes, dmem_bytes)
    layout  = MemoryLayout.from_config(config)
    out_dir = out_dir or os.path.join(DEFAULT_OUT, name)

    build  = compile_program(sources, layout, out_dir, march=march,
                             opt=opt, name=name)
    elf    = read_elf32(build.elf_path)
    report = verify_program(elf, config.isa)
    if verify:
        report.raise_if_bad()

    image = build_image(elf, layout)
    if write_files:
        image.write_files(out_dir)

    return Program(name=name, config=config, layout=layout, elf=elf,
                   image=image, build=build, report=report)
