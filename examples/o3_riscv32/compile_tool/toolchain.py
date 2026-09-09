# Driving the RISC-V toolchain: sources in, one linked ELF out.
#
# `march` is a parameter, so the same build serves rv32i today and rv32im the
# day the ISA description grows multiply µops. Both multilibs ship with the
# GNU toolchain, each with its own libgcc.
#
# -mstrict-align is NOT optional: a misaligned access is silently wrong in the
# load/store unit (docs/open_items.md), so the compiler must never emit one.
#
# LIMIT: -ffreestanding stops most of it, but GCC may still call memcpy or
# memset for a large struct copy. There is no libc, so that surfaces as an
# undefined reference at link time — loud, which is the point.

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence, Tuple

from .cheader import render_c_header
from .layout import MemoryLayout
from .ldscript import render_linker_script

# --- the tools ----------------------------------------------------------------

PREFIX_ENV  = "CAROLYNE_RISCV_PREFIX"
TOOL_PREFIX = os.environ.get(PREFIX_ENV, "riscv64-unknown-elf-")

RUNTIME_DIR = os.path.join(os.path.dirname(__file__), "runtime")
CRT0_NAME   = "crt0.S"
HEADER_NAME = "carolyne_io.h"
SCRIPT_NAME = "link.ld"

BASE_CFLAGS = ("-mabi=ilp32",
               "-mstrict-align",      # a misaligned access is silently wrong
               "-ffreestanding",      # no libc, no builtins that call one
               "-fno-pie",
               "-fno-common",
               "-Wall")


# --- what a build produced ----------------------------------------------------
@dataclass(frozen=True)
class BuildArtifacts:
    """Every file one build wrote, so a caller never rebuilds a path."""

    out_dir     : str                # every other path here is under it
    elf_path    : str                # the linked program, before flattening
    dump_path   : str                # objdump -d -S text, for reading the code
    script_path : str                # the GENERATED linker script, not a fixed one
    header_path : str                # the GENERATED carolyne_io.h the sources include
    march       : str                # which multilib was used: rv32i or rv32im
    objects     : Tuple[str, ...]    # crt0.o first, then one per source file


# --- steps --------------------------------------------------------------------
def write_support_files(layout: MemoryLayout, out_dir: str) -> Tuple[str, str, str]:
    """Put the generated script, header and startup code in the build dir.

    All three come from the layout, so the addresses a program compiles
    against are the addresses the machine was sized for.
    """
    os.makedirs(out_dir, exist_ok=True)

    script_path = os.path.join(out_dir, SCRIPT_NAME)
    header_path = os.path.join(out_dir, HEADER_NAME)
    crt0_path   = os.path.join(out_dir, CRT0_NAME)

    _write(script_path, render_linker_script(layout))
    _write(header_path, render_c_header(layout))
    shutil.copyfile(os.path.join(RUNTIME_DIR, CRT0_NAME), crt0_path)

    return script_path, header_path, crt0_path


def compile_program(sources : Sequence[str],
                    layout  : MemoryLayout,
                    out_dir : str,
                    march   : str = "rv32i",
                    opt     : str = "-O2",
                    name    : str = "program",
                    extra_cflags: Sequence[str] = ()) -> BuildArtifacts:
    """Assemble crt0, compile the C sources, link them against the script."""
    if not sources:
        raise ValueError("compile_program: no source files given")

    script_path, _, crt0_path = write_support_files(layout, out_dir)
    cflags = [f"-march={march}", *BASE_CFLAGS, opt, f"-I{out_dir}",
              *extra_cflags]

    # crt0 is prepended, not asked for, and takes only the architecture flags:
    # the C flags have nothing to act on in hand-written assembly.
    objects = [_assemble(crt0_path, out_dir, march)]
    objects += [_compile_one(src, out_dir, cflags) for src in sources]

    elf_path  = os.path.join(out_dir, f"{name}.elf")
    dump_path = os.path.join(out_dir, f"{name}.dump")
    _link(objects, script_path, elf_path, march)
    _write(dump_path, _run([_tool("objdump"), "-d", "-S", elf_path]).stdout)

    return BuildArtifacts(out_dir     = out_dir,
                          elf_path    = elf_path,
                          dump_path   = dump_path,
                          script_path = script_path,
                          header_path = os.path.join(out_dir, HEADER_NAME),
                          march       = march,
                          objects     = tuple(objects))


# --- one tool run each --------------------------------------------------------
def _assemble(path: str, out_dir: str, march: str) -> str:
    obj = os.path.join(out_dir, _obj_name(path))
    _run([_tool("gcc"), f"-march={march}", "-mabi=ilp32",
          "-c", path, "-o", obj])
    return obj


def _compile_one(path: str, out_dir: str, cflags: Sequence[str]) -> str:
    obj = os.path.join(out_dir, _obj_name(path))
    _run([_tool("gcc"), *cflags, "-c", path, "-o", obj])
    return obj


def _link(objects: Sequence[str], script: str, elf: str, march: str) -> None:
    """Link through gcc, not ld, so libgcc comes from the right multilib.

    -lgcc is stated explicitly because -nostdlib drops it, and a plain rv32i
    program needs it the moment it multiplies: with no M extension GCC turns
    `*` and `/` into calls to __mulsi3 and __divsi3.
    """
    _run([_tool("gcc"), f"-march={march}", "-mabi=ilp32",
          "-nostdlib", "-nostartfiles", "-static",
          f"-Wl,-T,{script}", "-Wl,--fatal-warnings",
          *objects, "-o", elf, "-lgcc"])


# --- helpers ------------------------------------------------------------------
def _tool(what: str) -> str: return f"{TOOL_PREFIX}{what}"


def _obj_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{stem}.o"


def _write(path: str, text: str) -> None:
    with open(path, "w") as handle:
        handle.write(text)


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    """Run one tool, and report its own message when it fails."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise RuntimeError(
            f"{argv[0]} not found. Set {PREFIX_ENV} if your toolchain uses "
            f"another prefix than '{TOOL_PREFIX}'.") from None

    if done.returncode:
        # the tool's own message first: it is what names the real problem
        said = done.stderr.strip() or done.stdout.strip()
        raise RuntimeError(
            f"{os.path.basename(argv[0])} failed (exit {done.returncode})\n"
            f"{said}\n\n  command: {' '.join(argv)}")
    return done
