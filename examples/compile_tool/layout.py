# Memory layout — the one place an address or a size is written down.
#
# Built from a MachineMem the CALLER states. A machine config DERIVES one
# (examples/o3's machine_mem_of reads the same per-memory specs the hardware
# sizes itself from, so nothing drifts from the RTL); a target with no machine
# states its own numbers (Target.machine_mem).
#
# Its consumers: the linker script (ldscript.py), the C header (cheader.py),
# the image writer (image.py), and the simulation that loads the images into
# the machine and watches its store port (examples/sim).
#
# The two memories are SEPARATE, so each region states its own base. The data
# base costs nothing: the load/store unit part-selects the word index down to
# data_mem_idx_width bits (uarch/o3/exec_unit.py, mem_index), so a base that is
# a multiple of the data memory size is truncated away before the memory sees
# it. A distinct base only makes the ELF and the disassembly readable.

from __future__ import annotations

from dataclasses import dataclass

from carolyne.util import is_power_of_two

# --- fixed choices ------------------------------------------------------------

DMEM_BASE = 0x10000000      # any multiple of the data memory size would serve

DEFAULT_IMEM_BYTES = 8 * 1024       # what a build gets when no size is stated
DEFAULT_DMEM_BYTES = 4 * 1024

# The CODE region is not chosen here: it starts at MachineMem.imem_base — the
# ISA's reset_pc — so the linker script and the fetch reset cannot disagree.
#
# 0x10000000, not 0x80000000: a pc-relative pair (auipc+addi, what `la` and
# `call` assemble to) reaches +-2GB, and 0x80000000 is exactly that far from a
# code region at 0, Rv32im's default reset vector — the edge of the range.

MMIO_BYTES = 16                                 # reserved at the TOP of the data region
MMIO_NAMES = ("putchar", "putint", "exit")      # one word each, in this order


# --- bytes to index width -------------------------------------------------------

def _idx_width_for(total_bytes: int, banks: int, word_bytes: int) -> int:
    """The index width one bank needs for a memory of this many bytes.

    - private twin of examples/o3/core/mem_size.idx_width_for: the tool may not
      import a machine package, and the size tests hold the two equal
    """
    for what, value in (("total_bytes", total_bytes), ("banks", banks),
                        ("word_bytes", word_bytes)):
        if not is_power_of_two(value):
            raise ValueError(
                f"MemoryLayout: {what} must be a power of two — the address "
                f"is a part-select, not a compare — got {value}")

    words_per_bank, remainder = divmod(total_bytes, banks * word_bytes)
    if remainder or words_per_bank < 1:
        raise ValueError(
            f"MemoryLayout: {total_bytes} bytes does not divide into {banks} "
            f"bank(s) of {word_bytes}-byte words")
    return words_per_bank.bit_length() - 1


# --- what the caller states -----------------------------------------------------
@dataclass(frozen=True)
class MachineMem:
    """The memories a program is laid out for — everything a build needs to
    know about the machine, stated by the CALLER.

    - a machine config DERIVES one (examples/o3's machine_mem_of), so the images
      and the hardware cannot disagree; a target with no machine states the
      numbers itself (Target.machine_mem)
    - pure data: from_spec() is where it is held to account, and the index
      widths are derived there — the store-the-count bargain
    """

    imem_base  : int      # where code starts: the ISA's reset_pc
    imem_bytes : int      # the WHOLE instruction memory, every bank together
    imem_banks : int      # one per fetch lane — a lane IS a bank
    dmem_base  : int      # a multiple of the memory size; the hardware truncates it away
    dmem_bytes : int      # the whole data memory, I/O words included
    word_bytes : int      # the bus width: 4 for RV32


# --- the layout ---------------------------------------------------------------
@dataclass(frozen=True)
class MemoryLayout:
    """Where code, data, the stack and the I/O words are, in bytes.

    - build it with from_spec(): one MachineMem in, every derived number out,
      so no address is ever written down twice
    - every address here is a BYTE address; image.py converts to word indices
    """

    #   instruction memory — one bank per fetch lane, interleaved
    #
    #     imem_base  0x00000000  ┌──────────────────────┐
    #                            │ .text                │
    #                            │ zeros to the end     │
    #     imem_limit 0x00002000  └──────────────────────┘
    #     imem_bytes = 2^imem_idx_width * imem_banks * word_bytes
    #
    #   data memory — one bank, word indexed
    #
    #     dmem_base  0x10000000  ┌──────────────────────┐
    #                            │ .rodata .data .bss   │
    #                            │ free                 │
    #                            │ stack, growing up    │
    #     data_limit 0x10000ff0  ├──────────────────────┤ <- stack_top
    #                            │ putchar putint exit  │
    #     dmem_limit 0x10001000  └──────────────────────┘
    #     dmem_bytes = 2^dmem_idx_width * word_bytes
    #
    #   Addresses are the 8K/4K default; the limits are properties below.

    imem_base      : int      # the ISA's reset_pc: .text and _start begin here
    imem_bytes     : int      # the WHOLE memory, every bank together
    imem_banks     : int      # one per fetch lane — a lane IS a bank
    imem_idx_width : int      # words in ONE bank, as a power of two
    dmem_base      : int      # truncated away by the hardware; readability only
    dmem_bytes     : int      # the whole memory, I/O words INCLUDED
    dmem_idx_width : int      # words in the single bank, as a power of two
    word_bytes     : int      # the data bus width: 4 for RV32

    # --- construction ---------------------------------------------------------
    @classmethod
    def from_spec(cls, machine_mem: MachineMem) -> "MemoryLayout":
        """The layout `machine_mem` describes.

        - _idx_width_for is what holds the sizes to account (powers of two,
          whole banks); the region and overlap checks are __post_init__'s
        """
        return cls(imem_base      = machine_mem.imem_base,
                   imem_bytes     = machine_mem.imem_bytes,
                   imem_banks     = machine_mem.imem_banks,
                   imem_idx_width = _idx_width_for(machine_mem.imem_bytes,
                                                   machine_mem.imem_banks,
                                                   machine_mem.word_bytes),
                   dmem_base      = machine_mem.dmem_base,
                   dmem_bytes     = machine_mem.dmem_bytes,
                   dmem_idx_width = _idx_width_for(machine_mem.dmem_bytes, 1,
                                                   machine_mem.word_bytes),
                   word_bytes     = machine_mem.word_bytes)

    def __post_init__(self) -> None:
        self._reject_bad_region("instruction", self.imem_base, self.imem_bytes)
        self._reject_bad_region("data",        self.dmem_base, self.dmem_bytes)

        if not is_power_of_two(self.word_bytes):
            raise ValueError(
                f"MemoryLayout: word_bytes must be a power of two, "
                f"got {self.word_bytes}")
        if (self.imem_base < self.dmem_limit
                and self.dmem_base < self.imem_limit):
            raise ValueError(
                f"MemoryLayout: the code region 0x{self.imem_base:08x}.."
                f"0x{self.imem_limit:08x} overlaps the data region "
                f"0x{self.dmem_base:08x}..0x{self.dmem_limit:08x} — the ISA's "
                f"reset_pc places the code, so pick a data base clear of it")
        if self.dmem_bytes <= MMIO_BYTES:
            raise ValueError(
                f"MemoryLayout: the data memory is {self.dmem_bytes} bytes, "
                f"which leaves nothing under the {MMIO_BYTES}-byte I/O window "
                f"at the top of the region")

    @staticmethod
    def _reject_bad_region(what: str, base: int, size: int) -> None:
        """A region must be a power of two and sit on its own size.

        The hardware part-selects the low address bits, so a base that is not a
        multiple of the size would not be stripped and every access would land
        somewhere else.
        """
        if not is_power_of_two(size):
            raise ValueError(
                f"MemoryLayout: the {what} memory must be a power of two "
                f"bytes — the address is a part-select, not a compare — "
                f"got {size}")
        if base % size:
            raise ValueError(
                f"MemoryLayout: the {what} base 0x{base:08x} is not a multiple "
                f"of its {size}-byte size, so the hardware would not truncate "
                f"it away")

    # --- code region ----------------------------------------------------------
    @property
    def imem_limit(self) -> int: return self.imem_base + self.imem_bytes

    @property
    def imem_words(self) -> int: return self.imem_bytes // self.word_bytes

    @property
    def reset_pc(self) -> int: return self.imem_base

    # --- data region ----------------------------------------------------------
    @property
    def dmem_limit(self) -> int: return self.dmem_base + self.dmem_bytes

    @property
    def dmem_words(self) -> int: return self.dmem_bytes // self.word_bytes

    @property
    def mmio_base(self) -> int: return self.dmem_limit - MMIO_BYTES

    @property
    def data_limit(self) -> int: return self.mmio_base

    @property
    def data_bytes(self) -> int: return self.data_limit - self.dmem_base

    @property
    def stack_top(self) -> int: return self.mmio_base

    # --- the I/O words --------------------------------------------------------
    @property
    def mmio_addrs(self) -> dict:
        """Each I/O word's byte address, keyed by name."""
        return {name: self.mmio_base + i * self.word_bytes
                for i, name in enumerate(MMIO_NAMES)}

    def mmio_name_at(self, addr: int) -> str:
        """The I/O word a store address names, or "" when it names none."""
        for name, at in self.mmio_addrs.items():
            if at == addr:
                return name
        return ""

    # --- what the hardware sees -----------------------------------------------
    def instr_slot(self, addr: int) -> tuple:
        """(bank, index) the instruction at this byte address is stored in.

        The banks are INTERLEAVED and a lane IS a bank (uarch/o3/fetch.py):
        word w is in bank w % banks at index w // banks.
        """
        word = (addr - self.imem_base) // self.word_bytes
        return word % self.imem_banks, word // self.imem_banks

    def data_index(self, addr: int) -> int:
        """The data memory word index a byte address reaches.

        The high bits are masked, not refused — that is what the hardware's
        part-select does, so an address past the region wraps here too.
        """
        return ((addr // self.word_bytes) & (self.dmem_words - 1))

    def describe(self) -> str:
        """The map as a table, for the CLI and for a build log."""
        rows = [("code",  self.imem_base,  self.imem_limit, f"{self.imem_banks} bank(s)"),
                ("data",  self.dmem_base,  self.data_limit, "data, bss, stack"),
                ("io",    self.mmio_base,  self.dmem_limit, " ".join(MMIO_NAMES))]
        wide = "\n".join(f"  {what:<5} 0x{lo:08x} .. 0x{hi:08x}  "
                         f"{hi - lo:>6} B  {note}"
                         for what, lo, hi, note in rows)
        return f"memory layout\n{wide}"
