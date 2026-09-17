# A build TARGET — everything about one ISA that the toolchain, the linker
# script, the ELF check and the verify step need, stated ONCE per ISA so the
# rest of the tool names no architecture.
#
# NOT here: a machine. A target is an ISA plus a toolchain; which core runs the
# program is the CALLER's choice, bound by target_named(name, config).
#
#   rv32im   RISC-V with multiply/divide — the ONE RISC-V target: the
#            description carries the M extension, so a no-M variant would buy
#            only a slower multiply through libgcc
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

from .elf32 import EM_MIPS, EM_RISCV
from .layout import DMEM_BASE, MachineMem
from .machine import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES

MIPS_RESET_PC = 0xBFC00000        # the architectural reset vector; a MIPS IsaBase will own it


@dataclass(frozen=True)
class Target:
    """One ISA as the tool sees it: its compiler, its runtime, its description."""

    name           : str                       # rv32im | mips32
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
    isa            : Optional[Callable[[], IsaBase]]         # the description verify holds a program to, or None

    def tool(self, what: str) -> str:
        return f"{os.environ.get(self.prefix_env, self.tool_prefix)}{what}"

    @property
    def can_verify(self) -> bool: return self.isa is not None

    def machine_mem(self,
                 imem_bytes : int = DEFAULT_IMEM_BYTES,
                 dmem_bytes : int = DEFAULT_DMEM_BYTES,
                 banks      : int = 1,
                 dmem_base  : int = DMEM_BASE) -> MachineMem:
        """The memories to lay out for, from this target's own facts.

        - the MACHINE-LESS path (and the CLI's): a target with a real machine
          derives its MachineMem from the config instead (examples/o3's
          machine_mem_of), so banks and sizes cannot disagree with the hardware
        """
        word = self.isa().dlen_bytes if self.can_verify else 4   # no description: 32-bit until one owns it
        return MachineMem(imem_base  = self.reset_pc,
                       imem_bytes = imem_bytes,
                       imem_banks = banks,
                       dmem_base  = dmem_base,
                       dmem_bytes = dmem_bytes,
                       word_bytes = word)


RV32IM = Target(
    name           = "rv32im",
    tool_prefix    = "riscv64-unknown-elf-",
    prefix_env     = "CAROLYNE_RISCV_PREFIX",
    arch_flags     = ("-march=rv32im", "-mabi=ilp32"),
    cflags         = ("-mstrict-align",),          # a misaligned access is silently wrong in the LS unit
    crt0           = "crt0_riscv.S",
    output_arch    = "riscv",
    gp_symbol      = "__global_pointer$ = . + 0x800;",
    discard        = (".riscv.attributes",),
    elf_machine    = EM_RISCV,
    reset_pc       = RV32_RESET_PC,
    isa            = Rv32im,
)

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
    isa            = None,
)

TARGETS = {target.name: target for target in (RV32IM, MIPS32)}


def target_named(name: str) -> Target:
    """The target by name, or a message listing the ones there are.

    - a target states an ISA and a toolchain, never a machine: the memories a
      build lays out for arrive as build_program's own `mem` (a MachineMem)
    """
    try:
        return TARGETS[name]
    except KeyError:
        raise ValueError(f"unknown target {name!r}; one of {', '.join(TARGETS)}") from None


def resolve_target(target: "str | Target") -> Target:
    return target if isinstance(target, Target) else target_named(target)
