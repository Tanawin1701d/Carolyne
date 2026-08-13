# Register-file metadata — the elaboration-plane description of one
# architectural register class (uop_contract.md §1.1). Pure data, no Kathryn
# imports: the uarch reads these numbers to size its RAT, free list, physical
# register file, and the src/dest index fields of the µop record.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class RegFile:
    name       : str                    # class name, e.g. "x", "gpr", "flags"
    width      : int                    # bits per architectural register
    amount     : int                    # number of architectural registers
    renamed    : bool = True            # False -> engine treats it as static state
    const_regs : Dict[int, int] = field(default_factory=dict)
                                        # arch idx -> hardwired value (RISC-V x0 -> 0);
                                        # rename bypasses reads to the constant,
                                        # writes are discarded

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("RegFile needs a non-empty name")
        if self.width < 1:
            raise ValueError(f"RegFile '{self.name}': width must be >= 1, got {self.width}")
        if self.amount < 1:
            raise ValueError(f"RegFile '{self.name}': amount must be >= 1, got {self.amount}")
        for idx, value in self.const_regs.items():
            if not (0 <= idx < self.amount):
                raise ValueError(
                    f"RegFile '{self.name}': const reg index {idx} out of range 0..{self.amount - 1}")
            if not (0 <= value < (1 << self.width)):
                raise ValueError(
                    f"RegFile '{self.name}': const value {value:#x} does not fit in {self.width} bits")

    @property
    def index_width(self) -> int:
        # Bits needed to address any register: ceil(log2(amount)). A
        # single-register file (e.g. flags) needs no index -> 0 bits.
        return (self.amount - 1).bit_length()

    def is_const(self, idx: int) -> bool:
        return idx in self.const_regs
