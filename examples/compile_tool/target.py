# A build TARGET — everything about one ISA that the toolchain, the linker
# script, the ELF check and the verify step need, stated ONCE per ISA so the
# rest of the tool names no architecture.
#
#   rv32i    RISC-V, the base ISA the description implements today
#   rv32im   RISC-V with multiply/divide (verify refuses M instructions until
#            the description grows them)
#   mips32   MIPS32r2, little-endian (mipsel). Multiply and divide are in the
#            MIPS32 base ISA, so there is no "im" variant to name.
#            LIMIT: no carolyne/isa/mips description yet, so a MIPS build is
#            laid out and linked but not verified.

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Callable, Optional, Tuple

from carolyne.isa import IsaBase
from carolyne.isa.riscv import Rv32im
from carolyne.isa.riscv.field_match import RESET_PC as RV32_RESET_PC
from carolyne.uarch.o3.config import CPUO3_Config

from .elf32 import EM_MIPS, EM_RISCV
from .machine import config_for_sizes

MIPS_RESET_PC = 0xBFC00000        # the architectural reset vector; a MIPS IsaBase will own it


@dataclass(frozen=True)
class Target:
    """One ISA as the tool sees it: its compiler, its runtime, its description."""

    name           : str                       # rv32i | rv32im | mips32
    tool_prefix    : str                       # the cross-compiler prefix, by default
    prefix_env     : str                       # the environment variable that overrides it
    arch_flags     : Tuple[str, ...]           # -march/-mabi: assemble, compile and link alike
    cflags         : Tuple[str, ...]           # the C flags this target adds to the shared ones
    crt0           : str                       # runtime/<file>: the reset vector and the C runtime
    output_arch    : str                       # the linker script's OUTPUT_ARCH
    gp_symbol      : str                       # the small-data anchor the linker script defines
    discard        : Tuple[str, ...]           # the arch note sections the linker script discards
    elf_machine    : int                       # the e_machine a linked ELF must carry
    reset_pc       : int                       # where the code starts when no machine config decides
    machine_config : Optional[Callable[..., CPUO3_Config]]   # (imem, dmem, lanes) -> the Carolyne machine, or None
    isa            : Optional[Callable[[], IsaBase]]         # the description verify holds a program to, or None

    def tool(self, what: str) -> str:
        return f"{os.environ.get(self.prefix_env, self.tool_prefix)}{what}"

    @property
    def can_verify(self) -> bool: return self.isa is not None


def rv32_config(imem_bytes: int, dmem_bytes: int, lanes: int) -> CPUO3_Config:
    return config_for_sizes(imem_bytes, dmem_bytes, fe_lanes=lanes)


RV32I = Target(
    name           = "rv32i",
    tool_prefix    = "riscv64-unknown-elf-",
    prefix_env     = "CAROLYNE_RISCV_PREFIX",
    arch_flags     = ("-march=rv32i", "-mabi=ilp32"),
    cflags         = ("-mstrict-align",),          # a misaligned access is silently wrong in the LS unit
    crt0           = "crt0_riscv.S",
    output_arch    = "riscv",
    gp_symbol      = "__global_pointer$ = . + 0x800;",
    discard        = (".riscv.attributes",),
    elf_machine    = EM_RISCV,
    reset_pc       = RV32_RESET_PC,
    machine_config = rv32_config,
    isa            = Rv32im,
)

RV32IM = replace(RV32I, name="rv32im", arch_flags=("-march=rv32im", "-mabi=ilp32"))

MIPS32 = Target(
    name           = "mips32",
    tool_prefix    = "mipsel-linux-gnu-",
    prefix_env     = "CAROLYNE_MIPS_PREFIX",
    arch_flags     = ("-march=mips32r2", "-mabi=32"),
    cflags         = ("-mno-abicalls", "-fno-pic", "-G0"),   # bare metal: no GOT, no gp-relative small data
    crt0           = "crt0_mips.S",
    output_arch    = "mips",
    gp_symbol      = "_gp = . + 0x7ff0;",
    discard        = (".MIPS.abiflags", ".MIPS.options", ".reginfo", ".mdebug.*", ".pdr", ".gnu.attributes"),
    elf_machine    = EM_MIPS,
    reset_pc       = MIPS_RESET_PC,
    machine_config = None,
    isa            = None,
)

TARGETS = {target.name: target for target in (RV32I, RV32IM, MIPS32)}


def target_named(name: str) -> Target:
    """The target by name, or a message listing the ones there are."""
    try:
        return TARGETS[name]
    except KeyError:
        raise ValueError(f"unknown target {name!r}; one of {', '.join(TARGETS)}") from None


def resolve_target(target: "str | Target") -> Target:
    return target if isinstance(target, Target) else target_named(target)
