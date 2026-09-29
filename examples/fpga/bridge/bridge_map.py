# THE HOST MAP — the window a host (the PS, or a testbench) sees when it looks
# at the machine through the HostBridge: which byte address is which register,
# which console entry, or which word of a memory.
#
# One definition, three readers: the bridge hardware decodes it, the driver
# addresses it, and the Vivado build sizes the AXI window from it. All three
# import THIS file, so an address is never written down twice.
#
#   region          bytes                  what a write / read there does
#   REGS            4096                   the registers below
#   CONSOLE_WORDS   4 * console_depth      entry i: the word the program stored
#   CONSOLE_TAGS    4 * console_depth      entry i: 0 = putchar, 1 = putint
#   IMEM            imem_bytes             write: word i of the instruction image
#   DMEM            dmem_bytes             write: word i of the data image
#
# Every region size is a power of two and each region starts at a multiple of
# its own size, so the bridge selects a region by comparing the high address
# bits and the low bits ARE the offset inside it.
#
# stdlib only: this file runs on the board.

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Dict, Tuple

MAP_VERSION = 1
MAGIC_WORD  = 0x43415231          # "CAR1", read back first to prove the link
WORD_BYTES  = 4                   # LIMIT: the bridge is a 32-bit window

# ---- regions ---------------------------------------------------------------------
REGS          = "regs"
CONSOLE_WORDS = "console_words"
CONSOLE_TAGS  = "console_tags"
IMEM          = "imem"
DMEM          = "dmem"
REGION_ORDER  = (REGS, CONSOLE_WORDS, CONSOLE_TAGS, IMEM, DMEM)

REGS_BYTES       = 4096
MIN_REGION_BYTES = 4096

# ---- registers: byte offsets inside REGS ------------------------------------------
REG_MAGIC         = 0x00        # r   MAGIC_WORD
REG_GEOMETRY      = 0x04        # r   the sizes this bridge was built for (geometry_word)
REG_CTRL          = 0x08        # w   CTRL_START
REG_STATUS        = 0x0C        # r   STATUS_* bits
REG_CYCLES        = 0x10        # r   edges from the read-lock release to the exit store
REG_EXIT_CODE     = 0x14        # r   the word stored to the exit door
REG_CONSOLE_COUNT = 0x18        # r   console entries captured
REG_CYCLE_LIMIT   = 0x1C        # rw  stop after this many cycles; 0 = never
REG_SCRATCH       = 0x20        # rw  a link test

CTRL_START = 1 << 0             # one write releases both read locks

STATUS_STARTED            = 1 << 0
STATUS_FINISHED           = 1 << 1
STATUS_EXIT_SEEN          = 1 << 2
STATUS_CYCLE_LIMIT_HIT    = 1 << 3
STATUS_CONSOLE_OVERFLOW   = 1 << 4
STATUS_HOST_WRITE_REFUSED = 1 << 5

TAG_PUTCHAR = 0
TAG_PUTINT  = 1

# ---- the top-level port names the bridge marks -------------------------------------
HOST_EN         = "host_en"
HOST_WE         = "host_we"
HOST_ADDR       = "host_addr"
HOST_WDATA      = "host_wdata"
HOST_RDATA      = "host_rdata"
HOST_PORT_NAMES = (HOST_EN, HOST_WE, HOST_ADDR, HOST_WDATA, HOST_RDATA)

# ---- the block-design cells the board reaches the bridge through -------------------
# Named here because the Vivado build creates them and the board driver looks
# them up in the overlay: one spelling for both.
HOST_BRAM_CELL  = "axi_bram_ctrl_host"      # the AXI BRAM controller in front of the window
RESET_GPIO_CELL = "axi_gpio_mrst"           # the AXI GPIO whose bit 0 is the machine's mrst


def is_power_of_two(value: int) -> bool: return value > 0 and value & (value - 1) == 0
def log2_exact     (value: int) -> int:  return value.bit_length() - 1
def next_power_of_two(value: int) -> int: return 1 if value <= 1 else 1 << (value - 1).bit_length()


@dataclass(frozen=True)
class HostMap:
    """The window's shape, derived from the machine's memory sizes."""

    imem_bytes    : int
    imem_banks    : int
    dmem_bytes    : int
    console_depth : int                 # entries the console buffer holds
    doors         : Dict[str, int]      # putchar / putint / exit as data WORD indices
    word_bytes    : int = WORD_BYTES

    def __post_init__(self) -> None:
        for what, value in (("imem_bytes", self.imem_bytes), ("imem_banks", self.imem_banks),
                            ("dmem_bytes", self.dmem_bytes), ("console_depth", self.console_depth)):
            if isinstance(value, bool) or not isinstance(value, int) or not is_power_of_two(value):
                raise ValueError(f"HostMap: {what} must be a power of two, got {value!r}")
        if self.console_depth < 2:
            raise ValueError(f"HostMap: console_depth must be >= 2, got {self.console_depth}")
        if self.word_bytes != WORD_BYTES:
            raise ValueError(f"HostMap: the bridge is a {WORD_BYTES}-byte window, got word_bytes={self.word_bytes}")
        if set(self.doors) != {"putchar", "putint", "exit"}:
            raise ValueError(f"HostMap: doors must name putchar, putint and exit, got {sorted(self.doors)}")
        object.__setattr__(self, "doors", dict(self.doors))

    # ---- the regions -----------------------------------------------------------
    @property
    def console_bytes(self) -> int:
        return max(self.console_depth * self.word_bytes, MIN_REGION_BYTES)

    @property
    def regions(self) -> Dict[str, Tuple[int, int]]:
        """name -> (base, size). Each base is a multiple of its own size."""
        sizes = {REGS         : REGS_BYTES,
                 CONSOLE_WORDS: self.console_bytes,
                 CONSOLE_TAGS : self.console_bytes,
                 IMEM         : self.imem_bytes,
                 DMEM         : self.dmem_bytes}
        placed, base = {}, 0
        for name in REGION_ORDER:
            size         = sizes[name]
            base         = (base + size - 1) // size * size
            placed[name] = (base, size)
            base        += size
        return placed

    @property
    def window_bytes(self) -> int:
        base, size = self.regions[REGION_ORDER[-1]]
        return next_power_of_two(base + size)

    @property
    def addr_bits(self) -> int: return log2_exact(self.window_bytes)

    def region_base(self, name: str) -> int: return self.regions[name][0]
    def region_size(self, name: str) -> int: return self.regions[name][1]

    def region_of(self, addr: int) -> Tuple[str, int]:
        """(region, offset inside it) for a byte address in the window."""
        for name, (base, size) in self.regions.items():
            if base <= addr < base + size:
                return name, addr - base
        raise ValueError(f"HostMap: address {addr:#x} is in no region (window is {self.window_bytes:#x} bytes)")

    def reg_addr(self, reg_offset: int) -> int: return self.region_base(REGS) + reg_offset

    def entry_addr(self, region: str, index: int) -> int:
        """The byte address of word `index` of a console or memory region."""
        base, size = self.regions[region]
        if not 0 <= index * self.word_bytes < size:
            raise ValueError(f"HostMap: index {index} is past region '{region}' ({size // self.word_bytes} words)")
        return base + index * self.word_bytes

    # ---- the geometry word ------------------------------------------------------
    @property
    def geometry_word(self) -> int:
        """What REG_GEOMETRY reads: the sizes, so a driver can refuse a stale bitstream."""
        return (log2_exact(self.imem_bytes)
                | log2_exact(self.dmem_bytes)    << 8
                | log2_exact(self.imem_banks)    << 16
                | log2_exact(self.console_depth) << 20
                | MAP_VERSION                    << 28)

    # ---- crossing a file ----------------------------------------------------------
    def to_dict(self) -> dict: return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HostMap": return cls(**data)

    def write_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=1)

    @classmethod
    def read_json(cls, path: str) -> "HostMap":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def describe(self) -> str:
        rows = [f"  {name:<14} {base:#08x}  {size:>7} bytes" for name, (base, size) in self.regions.items()]
        return "\n".join([f"host window: {self.window_bytes:#x} bytes ({self.addr_bits} address bits)", *rows])
