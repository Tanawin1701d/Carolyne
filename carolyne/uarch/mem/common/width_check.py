# WIDTH CHECKS for a memory port: hold a signal to the width the description
# states, and name the one that disagrees.
#
# A width mismatch is otherwise silent — Kathryn extends or truncates and the
# design still builds, so a wrong-sized address reaches memory as a WRONG
# address. `where` names the caller, the shape isa/'s check_matcher_pair uses.

from __future__ import annotations

from typing import Union

from kathryn.signal import SignalRef, to_ref

from carolyne.uarch.mem.common.addr_meta import AddrMeta

# One address region is either driven by a signal or fixed at an
# elaboration-time constant.
Source = Union[SignalRef, int]


def check_source_width(src: Source, width: int, where: str) -> None:
    """Hold one address source to the region it drives.

    - a signal must be EXACTLY as wide as the region: a mismatch would extend
      or truncate the address with no error
    - an int is a fixed region and must fit in the region's bits
    """
    if isinstance(src, SignalRef):
        got = to_ref(src)._slice.size
        if got != width:
            raise ValueError(f"{where}: source is {got} bits, region is {width}")
        return
    if isinstance(src, bool) or not isinstance(src, int):
        raise ValueError(
            f"{where}: must be a kathryn signal or an int, got {type(src).__name__}")
    if not 0 <= src < (1 << width):
        raise ValueError(f"{where}: constant {src:#x} does not fit in {width} bits")


def check_data_width(data: SignalRef, addr_meta: AddrMeta, where: str) -> None:
    """Hold a port's value signal to the data bus it moves through."""
    if not isinstance(data, SignalRef):
        raise ValueError(f"{where}: data must be a kathryn signal, got {type(data).__name__}")
    got = to_ref(data)._slice.size
    if got != addr_meta.data_bus_bits:
        raise ValueError(
            f"{where}: data is {got} bits, the bus is {addr_meta.data_bus_bits}")
