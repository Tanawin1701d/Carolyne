# The command line over build_program(). Thin on purpose: everything it does
# is one call into the package, so the API stays the thing worth reading.
#
#   python -m examples.compile_tool build hello.c
#   python -m examples.compile_tool build a.c b.c --target rv32im --imem 16K --dmem 8K
#   python -m examples.compile_tool build hello.c --target mips32
#   python -m examples.compile_tool layout --target mips32 --imem 16K
#   python -m examples.compile_tool verify out/hello.elf --target rv32i

from __future__ import annotations

import argparse
import sys

from .elf32 import read_elf32
from .machine import DEFAULT_DMEM_BYTES, DEFAULT_IMEM_BYTES
from .target import TARGETS, target_named
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
                      "Carolyne machine. No operating system.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_target(command):
        command.add_argument("--target", default="rv32i", choices=sorted(TARGETS),
                             help="rv32i (default), rv32im or mips32")

    def add_sizes(command):
        command.add_argument("--imem", type=parse_size,
                             default=DEFAULT_IMEM_BYTES,
                             help="instruction memory size (default 8K)")
        command.add_argument("--dmem", type=parse_size,
                             default=DEFAULT_DMEM_BYTES,
                             help="data memory size (default 4K)")
        command.add_argument("--lanes", type=int, default=2,
                             help="front-end lanes, one instruction bank each")

    build = sub.add_parser("build", help="compile sources into images")
    build.add_argument("sources", nargs="+")
    build.add_argument("--name", default="program")
    build.add_argument("--opt", default="-O2")
    build.add_argument("--out", default=None, help="output directory")
    build.add_argument("--no-verify", action="store_true",
                       help="skip the ISA check (for inspecting a program "
                            "the machine cannot run)")
    add_target(build)
    add_sizes(build)

    show = sub.add_parser("layout", help="print the memory map")
    add_target(show)
    add_sizes(show)

    check = sub.add_parser("verify", help="decode an ELF against the ISA")
    check.add_argument("elf")
    add_target(check)

    return parser


def main(argv=None) -> int:
    args   = build_parser().parse_args(argv)
    target = target_named(args.target)

    if args.command == "layout":
        from . import layout_for              # local: the layout pulls in the machine config
        _config, layout = layout_for(target, args.imem, args.dmem, args.lanes)
        print(f"target {target.name}\n\n{layout.describe()}")
        return 0

    if args.command == "verify":
        if not target.can_verify:
            raise ValueError(f"target {target.name} has no ISA description to verify against yet")
        report = verify_program(read_elf32(args.elf), target.isa())
        print(report.describe())
        if not report.ok:
            report.raise_if_bad()
        return 0

    from . import build_program            # local: the build pulls in the toolchain
    program = build_program(args.sources, target=target, name=args.name, opt=args.opt,
                            out_dir=args.out, imem_bytes=args.imem, dmem_bytes=args.dmem,
                            lanes=args.lanes, verify=not args.no_verify)
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
