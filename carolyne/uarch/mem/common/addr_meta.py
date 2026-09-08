# ADDRESS SHAPE — one address split into the bits that change and the low bits
# that are always zero:
#
#   | var_widths[0] | var_widths[1] | ... | ---- zero_width ---- |
#   |<--------- changes per access ------>|      always zero     |
#
# The changing half is stated as REGIONS, high region first, each one a part a
# port addresses on its own (bank select, row, column). A region is a SIZE,
# not a position: the regions stack directly on each other and on the zero
# part, so no fixed bit can stand between two of them.
#
# The zero part is what the data bus width guarantees: a bus of 2^zero_width
# bytes is only accessed on its own boundary, so a port does not carry those
# bits. Pure data, no Kathryn import — a port declaration reads these numbers
# to size its address wires.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from carolyne.params.constant import BYTE_WIDTH


@dataclass(frozen=True)
class AddrMeta:
    var_widths : Tuple[int, ...]    # bits that change, high region first
    zero_width : int                # low bits held at zero by the bus width

    def __post_init__(self) -> None:
        object.__setattr__(self, "var_widths", tuple(self.var_widths))  # accept any sequence
        for idx, width in enumerate(self.var_widths):
            if width < 0:
                raise ValueError(f"AddrMeta: var_widths[{idx}] must be >= 0, got {width}")
        if self.zero_width < 0:
            raise ValueError(f"AddrMeta: zero_width must be >= 0, got {self.zero_width}")
        if self.total_width < 1:
            raise ValueError(f"AddrMeta: total_width must be >= 1, got {self.total_width}")

    @property
    def total_var_width (self) -> int: return sum(self.var_widths)
    @property
    def total_width     (self) -> int: return self.total_var_width + self.zero_width
    @property
    def data_bus_bytes  (self) -> int: return 1 << self.zero_width
    @property
    def data_bus_bits   (self) -> int: return self.data_bus_bytes * BYTE_WIDTH
