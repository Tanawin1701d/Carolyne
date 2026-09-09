# The command line over build_program(). Thin on purpose: everything it does
# is one call into the package, so the API stays the thing worth reading.
#
#   python -m examples.o3_riscv32.compile_tool build hello.c
#   python -m examples.o3_riscv32.compile_tool build a.c b.c --imem 16K --dmem 8K
#   python -m examples.o3_riscv32.compile_tool layout --imem 16K
#   python -m examples.o3_riscv32.compile_tool verify out/hello.elf

from __future__ import annotations

import argparse
import sys

from carolyne.isa.riscv import Rv32i

from .elf32 import read_elf32
from .layout import MemoryLayout
from .machine import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES, config_for_sizes
from .verify import verify_program

_SUFFIXES = {"k": 1024, "m": 1024 * 1024}


def parse_size(text: str) -> int:
    """A byte count, with an optional K or M suffix: 8192, 8K, 1M."""
    cleaned = text.strip().lower().rstrip("ib")
    scale   = _SUFFIXES.get(cleaned[-1:], 1)
    digits  = cleaned[:-1] if scale > 1 else cleaned
    try:
        return int(digits, 0) * scale
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"'{text}' is not a size — try 8192, 8K or 1M") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "compile_tool",
        description = "Compile C into one memory image per memory, for a "
                      "Carolyne RV32I machine. No operating system.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_sizes(target):
        target.add_argument("--imem", type=parse_size,
                            default=DEFAULT_IMEM_BYTES,
                            help="instruction memory size (default 8K)")
        target.add_argument("--dmem", type=parse_size,
                            default=DEFAULT_DMEM_BYTES,
                            help="data memory size (default 4K)")
        target.add_argument("--lanes", type=int, default=2,
                            help="front-end lanes, one instruction bank each")

    build = sub.add_parser("build", help="compile sources into images")
    build.add_argument("sources", nargs="+")
    build.add_argument("--name", default="program")
    build.add_argument("--march", default="rv32i",
                       help="rv32i (default) or rv32im")
    build.add_argument("--opt", default="-O2")
    build.add_argument("--out", default=None, help="output directory")
    build.add_argument("--no-verify", action="store_true",
                       help="skip the ISA check (for inspecting a program "
                            "the machine cannot run)")
    add_sizes(build)

    show = sub.add_parser("layout", help="print the memory map")
    add_sizes(show)

    check = sub.add_parser("verify", help="decode an ELF against the ISA")
    check.add_argument("elf")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "layout":
        config = config_for_sizes(args.imem, args.dmem, fe_lanes=args.lanes)
        print(MemoryLayout.from_config(config).describe())
        return 0

    if args.command == "verify":
        report = verify_program(read_elf32(args.elf), Rv32i())
        print(report.describe())
        if not report.ok:
            report.raise_if_bad()
        return 0

    from . import build_program            # local: the build pulls in the toolchain
    config  = config_for_sizes(args.imem, args.dmem, fe_lanes=args.lanes)
    program = build_program(args.sources, name=args.name, march=args.march,
                            opt=args.opt, out_dir=args.out, config=config,
                            verify=not args.no_verify)
    print(program.describe())
    print(f"\nimages written to {program.build.out_dir}")
    return 0


def run() -> None:
    """Entry point that reports a build failure as a message, not a traceback."""
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        sys.exit(1)
