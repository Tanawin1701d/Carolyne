# The census: what a target's compiler actually emits for the test programs,
# before any hardware runs them.
#
#   python -m examples.compile_tool.census --target mips32 --opt=-O0 --opt=-O2
#
# Builds every program (verify OFF: this is the survey the description is
# held to, not the other way round), reads the objdump text the build
# writes, and reports:
#   histogram  every mnemonic, with how often it appears
#   (a) scope  mnemonics outside the target's described set + assembler aliases
#   (b) slots  a branch or jump whose next word is not the delay-slot nop
#   (c) libgcc `__*` text symbols in the ELF: a library member was pulled in
# The exit code is 1 when any of (a)–(c) fires. The scope set is DERIVED from
# the description (the µop names), so it cannot drift from the ISA.

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import re
import subprocess
import sys
from typing import Dict, List, Sequence, Set, Tuple

from . import build_program
from .target import Target, target_named

REPO     = pathlib.Path(__file__).resolve().parents[2]
PROGRAMS = REPO / "examples" / "compile_tool" / "programs"
OUT      = REPO / "generated" / "census"

# objdump -d: "bfc00000:\t3c1c0000 \tlui\tgp,0x0"
_LINE = re.compile(r"^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(\S+)\s*(.*)$")

# what the assembler prints for a described encoding under another name
ALIASES = {"nop", "ssnop", "ehb", "b", "bal", "beqz", "bnez", "move", "li",
           "negu", "neg", "not"}
# the control transfers whose next word is a delay slot
CONTROL = {"b", "bal", "beq", "bne", "beqz", "bnez", "blez", "bgtz", "bltz", "bgez",
           "bltzal", "bgezal", "j", "jal", "jr", "jalr"}


def scope_of(target: Target) -> Set[str]:
    """Every mnemonic the description names, lower-cased, plus the aliases."""
    return {uop.name.lower() for uop in target.isa().uops} | ALIASES


def read_dump(path: str) -> List[Tuple[int, int, str]]:
    """(addr, word, mnemonic) per instruction line of an objdump -d text."""
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        hit = _LINE.match(line)
        if hit:
            rows.append((int(hit.group(1), 16), int(hit.group(2), 16), hit.group(3)))
    return rows


def libgcc_symbols(target: Target, elf_path: str) -> List[str]:
    out = subprocess.run([target.tool("nm"), elf_path], capture_output=True, text=True).stdout
    return sorted(sym for line in out.splitlines()
                  for parts in [line.split()]
                  if len(parts) == 3 and parts[1] in "TtWw" and parts[2].startswith("__")
                  for sym in [parts[2]])


def survey(program: str, target: Target, opt: str, dmem: int, banks: int):
    """Build one program and read what came out."""
    stem = pathlib.Path(program).stem
    out  = OUT / f"{stem}_{target.name}_{opt.lstrip('-').lower()}"
    built = build_program([program], target.machine_mem(dmem_bytes=dmem, banks=banks),
                          target=target, name=stem, opt=opt, out_dir=str(out), verify=False)
    rows  = read_dump(built.build.dump_path)
    words = {addr: (word, mnemonic) for addr, word, mnemonic in rows}
    hist  = collections.Counter(mnemonic for _a, _w, mnemonic in rows)

    scope    = scope_of(target)
    outside  = sorted(m for m in hist if m not in scope)
    bad_slot = [(addr, mnemonic, words.get(addr + 4, (None, "?")))
                for addr, _word, mnemonic in rows
                if mnemonic in CONTROL and target.delay_slot_nop is not None
                and (addr + 4 not in words or words[addr + 4][0] != target.delay_slot_nop)]
    pulled   = libgcc_symbols(target, built.build.elf_path)
    return hist, outside, bad_slot, pulled, built.report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="census")
    parser.add_argument("--target", default="mips32")
    parser.add_argument("--opt", action="append", default=None)
    parser.add_argument("--dmem", type=int, default=16384)
    parser.add_argument("--lanes", type=int, default=2)
    parser.add_argument("programs", nargs="*")
    args = parser.parse_args(argv)

    target   = target_named(args.target)
    opts     = args.opt or ["-O0", "-O2"]
    programs = args.programs or sorted(str(p) for p in PROGRAMS.glob("*.c"))
    total    = collections.Counter()
    failed   = False

    for opt in opts:
        for program in programs:
            hist, outside, bad_slot, pulled, report = survey(program, target, opt,
                                                             args.dmem, args.lanes)
            total.update(hist)
            stem = pathlib.Path(program).stem
            print(f"{stem:<12} {opt:<4} {sum(hist.values()):>5} instructions  "
                  f"{len(hist):>3} mnemonics  {report.describe()}")
            for mnemonic in outside:
                failed = True
                print(f"    (a) outside the scope: {mnemonic} x{hist[mnemonic]}")
            for addr, mnemonic, (word, next_mnemonic) in bad_slot:
                failed = True
                shown = f"{word:08x} {next_mnemonic}" if word is not None else "(end of text)"
                print(f"    (b) delay slot at 0x{addr:08x} after {mnemonic}: {shown}")
            for sym in pulled:
                failed = True
                print(f"    (c) libgcc symbol linked: {sym}")

    print("\nmnemonic histogram, all programs and levels:")
    for mnemonic, count in sorted(total.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {mnemonic:<10} {count:>6}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
