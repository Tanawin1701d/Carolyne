# ELF32 section reader — just enough to flatten a linked program.
#
# The SECTION table, not the program header table: a section states its own
# address and carries the ALLOC flag, which is all a flat image needs, and it
# tells .bss (SHT_NOBITS, no file bytes) from initialised data. This is the
# same choice RIDECORE's memgen makes, and it is why no ELF library is needed.
#
# Little-endian ELF32 only. Anything else is refused by name rather than
# misread — a 64-bit or big-endian file would parse into nonsense.

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Tuple

# --- the constants this reader knows ------------------------------------------

ELF_MAGIC   = b"\x7fELF"
ELFCLASS32  = 1
ELFDATA2LSB = 1

ET_EXEC  = 2
EM_RISCV = 243

SHF_ALLOC     = 0x2
SHF_EXECINSTR = 0x4
SHT_NOBITS    = 8

_EHDR   = struct.Struct("<16sHHIIIIIHHHHHH")     # the whole ELF32 header
_SHDR   = struct.Struct("<10I")                  # one section header, 40 bytes
_SH_LEN = 40


# --- one section --------------------------------------------------------------
@dataclass(frozen=True)
class Section:
    """One entry of the section header table."""

    # Two of these are positions and mean completely different things, so
    # each says which space it is in. Copying a section is "take size_bytes
    # from offset_in_elf, put them at addr_target_mem".
    name            : str       # ".text", ".rodata" — resolved from .shstrtab
    type            : int       # sh_type: PROGBITS, NOBITS, SYMTAB …
    flags           : int       # sh_flags: ALLOC, WRITE, EXECINSTR
    addr_target_mem : int       # where it goes in the MACHINE'S memory
    offset_in_elf   : int       # where its bytes are in THIS FILE
    size_bytes      : int       # how many bytes, in both spaces

    @property
    def is_alloc(self)  -> bool: return bool(self.flags & SHF_ALLOC)

    @property
    def is_exec(self)   -> bool: return bool(self.flags & SHF_EXECINSTR)

    @property
    def is_nobits(self) -> bool: return self.type == SHT_NOBITS

    @property
    def limit_target_mem(self) -> int:
        return self.addr_target_mem + self.size_bytes


# --- the file -----------------------------------------------------------------
@dataclass(frozen=True)
class Elf32:
    """A linked ELF32 executable, read for its allocatable sections."""

    path     : str
    entry    : int
    machine  : int
    sections : Tuple[Section, ...]
    _raw     : bytes

    def bytes_of(self, section: Section) -> bytes:
        """The section's file bytes — zeros for a NOBITS section.

        A NOBITS section (.bss) states a size and an address but occupies no
        file space, so its content is defined to be zero.
        """
        if section.is_nobits:
            return bytes(section.size_bytes)
        start = section.offset_in_elf
        return self._raw[start:start + section.size_bytes]

    def alloc_sections(self) -> Tuple[Section, ...]:
        """The sections that occupy memory, in address order.

        A section without SHF_ALLOC never reaches the machine — .comment and
        .riscv.attributes both claim address 0 and would otherwise land on the
        reset vector.
        """
        return tuple(sorted((s for s in self.sections
                             if s.is_alloc and s.size_bytes),
                            key=lambda s: s.addr_target_mem))


# --- reading ------------------------------------------------------------------
def read_elf32(path: str) -> Elf32:
    """Parse a little-endian ELF32 executable's section table."""
    with open(path, "rb") as handle:
        raw = handle.read()

    _reject_bad_header(raw, path)
    # The ELF32 header, all 14 fields in order. Positional unpacking names
    # every one or none, so the seven this parser never reads become `_`.
    #
    #   e_ident      16 magic bytes — checked by _reject_bad_header
    #   e_type       REL, EXEC or DYN — must be EXEC, so addresses are final
    #   e_machine    which ISA; 0xf3 is RISC-V — recorded, never enforced
    #   e_version    always 1
    #   e_entry      address of the first instruction
    #   e_phoff      program header table — the OS loader's view, unused here
    #   e_shoff      section header table — what this parser walks
    #   e_flags      ISA-specific ABI flags
    #   e_ehsize     this header's own size, 52
    #   e_phentsize  one program header's size
    #   e_phnum      how many program headers
    #   e_shentsize  one section header's size, 40 — the stride used below
    #   e_shnum      how many section headers
    #   e_shstrndx   WHICH section holds every section's name
    (_, e_type, e_machine, _, e_entry, _, e_shoff,
     _, _, _, _, e_shentsize, e_shnum, e_shstrndx) = _EHDR.unpack_from(raw, 0)

    if e_type != ET_EXEC:
        raise ValueError(
            f"{path}: not a linked executable (e_type {e_type}, want "
            f"{ET_EXEC}) — a relocatable object states no final addresses")
    if e_shentsize != _SH_LEN:
        raise ValueError(
            f"{path}: section headers are {e_shentsize} bytes, want {_SH_LEN}")

    # One section header is ten 32-bit fields (_SHDR = "<10I"), 40 bytes. The
    # code below reads them by index, so this is what each index is:
    #
    #   [0] sh_name       offset into .shstrtab — a number, not text
    #   [1] sh_type       PROGBITS, NOBITS, SYMTAB, STRTAB, RELA …
    #   [2] sh_flags      ALLOC, WRITE, EXECINSTR
    #   [3] sh_addr       where the bytes go in MEMORY — 0 in a .o
    #   [4] sh_offset     where the bytes are in the FILE
    #   [5] sh_size       how many bytes
    #   [6] sh_link       meaning depends on sh_type    — unused here
    #   [7] sh_info       meaning depends on sh_type    — unused here
    #   [8] sh_addralign  required alignment            — unused here
    #   [9] sh_entsize    one entry's size in a table   — unused here
    #
    # [3] and [4] are the pair to keep straight: .rodata sits at 0x10000000
    # in memory and at 0x2000 in the file. image.py copies from [4] to [3].
    raw_headers = [_SHDR.unpack_from(raw, e_shoff + e_shentsize * i)
                   for i in range(e_shnum)]
    str_off     = raw_headers[e_shstrndx][4]        # sh_offset of .shstrtab

    sections = tuple(
        Section(name            = _string_at(raw, str_off + head[0]),
                type            = head[1],
                flags           = head[2],
                addr_target_mem = head[3],
                offset_in_elf   = head[4],
                size_bytes      = head[5])
        for head in raw_headers)

    return Elf32(path=path, entry=e_entry, machine=e_machine,
                 sections=sections, _raw=raw)


def _reject_bad_header(raw: bytes, path: str) -> None:
    """Refuse anything this reader would silently misread."""
    if len(raw) < _EHDR.size or raw[:4] != ELF_MAGIC:
        raise ValueError(f"{path}: not an ELF file")
    if raw[4] != ELFCLASS32:
        raise ValueError(f"{path}: not ELF32 (EI_CLASS {raw[4]})")
    if raw[5] != ELFDATA2LSB:
        raise ValueError(f"{path}: not little-endian (EI_DATA {raw[5]})")


def _string_at(raw: bytes, offset: int) -> str:
    """One NUL-terminated name out of a string table."""
    end = raw.index(b"\0", offset)
    return raw[offset:end].decode("ascii", "replace")
