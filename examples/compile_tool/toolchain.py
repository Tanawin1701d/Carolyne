# Driving the cross toolchain: sources in, one linked ELF out.
#
# Which compiler, which -march/-mabi, which crt0 and which linker OUTPUT_ARCH
# all come from the Target (target.py); nothing here names an architecture.
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
from .target import Target

# --- the tools ----------------------------------------------------------------

RUNTIME_DIR = os.path.join(os.path.dirname(__file__), "runtime")
HEADER_NAME = "carolyne_io.h"
SCRIPT_NAME = "link.ld"

BASE_CFLAGS = ("-ffreestanding",      # no libc, no builtins that call one
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
    target      : str                # which target was built: rv32i, rv32im, mips32
    objects     : Tuple[str, ...]    # crt0.o first, then one per source file


# --- steps --------------------------------------------------------------------
def write_support_files(layout: MemoryLayout, out_dir: str, target: Target) -> Tuple[str, str, str]:
    """Put the generated script, header and startup code in the build dir.

    All three come from the layout, so the addresses a program compiles
    against are the addresses the machine was sized for; the script and the
    startup code are the target's.
    """
    os.makedirs(out_dir, exist_ok=True)

    script_path = os.path.join(out_dir, SCRIPT_NAME)
    header_path = os.path.join(out_dir, HEADER_NAME)
    crt0_path   = os.path.join(out_dir, target.crt0)

    _write(script_path, render_linker_script(layout, target))
    _write(header_path, render_c_header(layout))
    shutil.copyfile(os.path.join(RUNTIME_DIR, target.crt0), crt0_path)

    return script_path, header_path, crt0_path


def compile_program(sources : Sequence[str],
                    layout  : MemoryLayout,
                    out_dir : str,
                    target  : Target,
                    opt     : str = "-O2",
                    name    : str = "program",
                    extra_cflags: Sequence[str] = ()) -> BuildArtifacts:
    """Assemble crt0, compile the C sources, link them against the script."""
    if not sources:
        raise ValueError("compile_program: no source files given")

    script_path, _, crt0_path = write_support_files(layout, out_dir, target)
    cflags = [*target.arch_flags, *target.cflags, *BASE_CFLAGS, opt, f"-I{out_dir}",
              *extra_cflags]

    # crt0 is prepended, not asked for, and takes only the architecture flags:
    # the C flags have nothing to act on in hand-written assembly.
    objects = [_assemble(crt0_path, out_dir, target)]
    objects += [_compile_one(src, out_dir, cflags, target) for src in sources]

    elf_path  = os.path.join(out_dir, f"{name}.elf")
    dump_path = os.path.join(out_dir, f"{name}.dump")
    _link(objects, script_path, elf_path, target)
    _write(dump_path, _run(target, [target.tool("objdump"), "-d", "-S", elf_path]).stdout)

    return BuildArtifacts(out_dir     = out_dir,
                          elf_path    = elf_path,
                          dump_path   = dump_path,
                          script_path = script_path,
                          header_path = os.path.join(out_dir, HEADER_NAME),
                          target      = target.name,
                          objects     = tuple(objects))


# --- one tool run each --------------------------------------------------------
def _assemble(path: str, out_dir: str, target: Target) -> str:
    obj = os.path.join(out_dir, _obj_name(path))
    _run(target, [target.tool("gcc"), *target.arch_flags, "-c", path, "-o", obj])
    return obj


def _compile_one(path: str, out_dir: str, cflags: Sequence[str], target: Target) -> str:
    obj = os.path.join(out_dir, _obj_name(path))
    _run(target, [target.tool("gcc"), *cflags, "-c", path, "-o", obj])
    return obj


def _link(objects: Sequence[str], script: str, elf: str, target: Target) -> None:
    """Link through gcc, not ld, so libgcc comes from the right multilib.

    -lgcc is stated explicitly because -nostdlib drops it, and a plain rv32i
    program needs it the moment it multiplies: with no M extension GCC turns
    `*` and `/` into calls to __mulsi3 and __divsi3.
    """
    _run(target, [target.tool("gcc"), *target.arch_flags,
                  "-nostdlib", "-nostartfiles", "-static",
                  f"-Wl,-T,{script}", "-Wl,--fatal-warnings",
                  *objects, "-o", elf, "-lgcc"])


# --- helpers ------------------------------------------------------------------


def _obj_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{stem}.o"


def _write(path: str, text: str) -> None:
    with open(path, "w") as handle:
        handle.write(text)


def _run(target: Target, argv: Sequence[str]) -> subprocess.CompletedProcess:
    """Run one tool, and report its own message when it fails."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise RuntimeError(
            f"{argv[0]} not found. Set {target.prefix_env} if your toolchain uses "
            f"another prefix than '{target.tool_prefix}'.") from None

    if done.returncode:
        # the tool's own message first: it is what names the real problem
        said = done.stderr.strip() or done.stdout.strip()
        raise RuntimeError(
            f"{os.path.basename(argv[0])} failed (exit {done.returncode})\n"
            f"{said}\n\n  command: {' '.join(argv)}")
    return done
