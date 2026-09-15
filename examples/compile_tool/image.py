# ELF to memory images — one image per memory, as the hardware stores them.
#
# The rule is memgen's: a zeroed buffer per region, then every SHF_ALLOC
# section copied to its own link address, with a NOBITS section (.bss)
# contributing zeros. A section without the ALLOC flag never reaches the
# machine.
#
# The instruction memory is then DE-INTERLEAVED. The banks are one per fetch
# lane and a lane IS a bank (uarch/o3/fetch.py), so word w is stored in bank
# w % banks at index w // banks. The split is done through
# MemoryLayout.instr_slot, so the rule is written once and the images cannot
# disagree with the fetch stage about it.

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Tuple

from .elf32 import Elf32, Section
from .layout import MemoryLayout


# --- one bank's contents ------------------------------------------------------
@dataclass(frozen=True)
class BankImage:
    """One memory bank, as a list of words."""

    name       : str
    words      : Tuple[int, ...]
    word_bytes : int

    @property
    def used_words(self) -> int:
        """Words up to the last non-zero one — what the program actually fills."""
        for i in range(len(self.words) - 1, -1, -1):
            if self.words[i]:
                return i + 1
        return 0

    def to_hex(self) -> str:
        """Verilog $readmemh text: one word per line, no prefix."""
        digits = self.word_bytes * 2
        return "".join(f"{word:0{digits}x}\n" for word in self.words)

    def to_bytes(self) -> bytes:
        """The raw little-endian image."""
        return b"".join(word.to_bytes(self.word_bytes, "little")
                        for word in self.words)


# --- where a section landed ---------------------------------------------------
@dataclass(frozen=True)
class Placement:
    """One allocated section and the region it was written into."""

    section : str
    region  : str
    addr    : int
    size    : int
    zeroed  : bool


# --- the whole program --------------------------------------------------------
@dataclass(frozen=True)
class ProgramImage:
    """Both memories' contents, ready to write out or to poke into a sim."""

    layout      : MemoryLayout
    instr_banks : Tuple[BankImage, ...]
    data_bank   : BankImage
    entry       : int
    placements  : Tuple[Placement, ...]

    def write_files(self, out_dir: str) -> Dict[str, str]:
        """Write one hex and one bin per bank; return the paths by name."""
        os.makedirs(out_dir, exist_ok=True)
        written = {}
        for bank in (*self.instr_banks, self.data_bank):
            for suffix, blob in (("hex", bank.to_hex()),
                                 ("bin", bank.to_bytes())):
                path = os.path.join(out_dir, f"{bank.name}.{suffix}")
                mode = "w" if suffix == "hex" else "wb"
                with open(path, mode) as handle:
                    handle.write(blob)
                written[f"{bank.name}.{suffix}"] = path
        return written

    def describe(self) -> str:
        """What went where, and how full each memory is."""
        rows = "\n".join(
            f"  {p.section:<12} {p.region:<5} 0x{p.addr:08x} "
            f"{p.size:>6} B{'  (zeros)' if p.zeroed else ''}"
            for p in self.placements)
        usage = "\n".join(
            f"  {b.name:<12} {b.used_words:>5} / {len(b.words):<5} words used"
            for b in (*self.instr_banks, self.data_bank))
        return f"sections\n{rows}\n\nimages\n{usage}"


# --- building -----------------------------------------------------------------
def build_image(elf: Elf32, layout: MemoryLayout) -> ProgramImage:
    """Flatten a linked ELF into one image per memory."""
    instr_flat = bytearray(layout.imem_bytes)
    data_flat  = bytearray(layout.dmem_bytes)
    buffers    = {"imem": (instr_flat, layout.imem_base),
                  "dmem": (data_flat,  layout.dmem_base)}
    placements = []

    for section in elf.alloc_sections():
        region        = _region_of(section, layout)
        buffer, base  = buffers[region]
        start         = section.addr_target_mem - base
        buffer[start:start + section.size_bytes] = elf.bytes_of(section)
        placements.append(Placement(section = section.name,
                                    region  = region,
                                    addr    = section.addr_target_mem,
                                    size    = section.size_bytes,
                                    zeroed  = section.is_nobits))

    return ProgramImage(layout      = layout,
                        instr_banks = _split_banks(instr_flat, layout),
                        data_bank   = _data_bank(data_flat, layout),
                        entry       = elf.entry,
                        placements  = tuple(placements))


def _region_of(section: Section, layout: MemoryLayout) -> str:
    """Which memory a section belongs to, refusing one that fits neither.

    A section that straddles a region end, or reaches into the I/O window at
    the top of the data region, is a linker-script problem — say so here
    rather than write bytes the machine will never read.
    """
    lo, hi = section.addr_target_mem, section.limit_target_mem
    if layout.imem_base <= lo and hi <= layout.imem_limit:
        return "imem"
    if layout.dmem_base <= lo and hi <= layout.data_limit:
        return "dmem"

    raise ValueError(
        f"section '{section.name}' at 0x{section.addr_target_mem:08x}.."
        f"0x{section.limit_target_mem:08x} ({section.size_bytes} bytes) fits "
        f"neither memory: code is "
        f"0x{layout.imem_base:08x}..0x{layout.imem_limit:08x}, data is "
        f"0x{layout.dmem_base:08x}..0x{layout.data_limit:08x} "
        f"(the {layout.dmem_limit - layout.data_limit} bytes above the data "
        f"region are the I/O words)")


def _split_banks(flat: bytearray, layout: MemoryLayout) -> Tuple[BankImage, ...]:
    """De-interleave the flat code image into one list of words per bank."""
    width = layout.word_bytes
    per   = layout.imem_words // layout.imem_banks
    banks = [[0] * per for _ in range(layout.imem_banks)]

    for word in range(layout.imem_words):
        addr        = layout.imem_base + word * width
        bank, index = layout.instr_slot(addr)
        offset      = word * width
        banks[bank][index] = int.from_bytes(flat[offset:offset + width],
                                            "little")

    return tuple(BankImage(f"imem_bank{b}", tuple(words), width)
                 for b, words in enumerate(banks))


def _data_bank(flat: bytearray, layout: MemoryLayout) -> BankImage:
    """The data memory: one bank, words in address order."""
    width = layout.word_bytes
    words = tuple(int.from_bytes(flat[i:i + width], "little")
                  for i in range(0, layout.dmem_bytes, width))
    return BankImage("dmem", words, width)
