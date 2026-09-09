# MEMORY PORT — one access gathered into one object: the address it names, the
# arbiter it synchronizes on, when it answers, and the signal its value moves
# through.
#
# The port CREATES NOTHING. The memory declares the PipCon, and whichever side
# owns a value declares its signal; this class only gathers the handles, so one
# object is the whole wiring between a requestor and a memory.
#
# The address covers the VAR REGIONS only, one source per region, high region
# first. The zero part of an AddrMeta is never carried — that is what splitting
# it off is for.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from kathryn import PipCon
from kathryn.signal import SignalRef

from carolyne.uarch.mem.common.addr_meta   import AddrMeta
from carolyne.uarch.mem.common.width_check import (Source, check_data_width,
                                                   check_source_width)


class PortTiming(Enum):
    """When the port answers, relative to the clock edge."""
    NEXT_EDGE = "next_edge"     # registered: the value is valid the NEXT cycle
    LEVEL     = "level"         # combinational: valid the SAME cycle


# --- the port -----------------------------------------------------------------

# eq=False: `==` on a Kathryn signal builds a comparison NODE, so a generated
# __eq__ would emit hardware instead of answering a bool.
@dataclass(frozen=True, eq=False)
class MemPortBase:
    """One access, gathered. Every handle in it is declared somewhere else."""
    addr_meta : AddrMeta
    addr_srcs : Tuple[Source, ...]      # one per var region, high region first
    pip_meta  : PipCon                  # declared by the memory, gathered here
    timing    : PortTiming

    def __post_init__(self) -> None:
        object.__setattr__(self, "addr_srcs", tuple(self.addr_srcs))  # accept any sequence
        where = type(self).__name__
        if not isinstance(self.addr_meta, AddrMeta):
            raise ValueError(
                f"{where}: addr_meta must be an AddrMeta, got {type(self.addr_meta).__name__}")
        widths = self.addr_meta.var_widths
        if len(self.addr_srcs) != len(widths):
            raise ValueError(
                f"{where}: needs one addr source per var region, got "
                f"{len(self.addr_srcs)} for {len(widths)} regions")
        for idx, (src, width) in enumerate(zip(self.addr_srcs, widths)):
            check_source_width(src, width, f"{where}: addr_srcs[{idx}]")
        if not isinstance(self.pip_meta, PipCon):
            raise ValueError(
                f"{where}: pip_meta must be a PipCon, got {type(self.pip_meta).__name__}")
        if not isinstance(self.timing, PortTiming):
            raise ValueError(
                f"{where}: timing must be a PortTiming, got {type(self.timing).__name__}")

    def bind_byte_addr(self, byte_addr) -> None:
        """Drive every region from ONE byte address, split by the shape.

        The regions stack straight onto the zero part, so each is a plain
        part-select: a caller states an address once instead of cutting it up.
        """
        low, parts = self.addr_meta.zero_width, []
        for width in reversed(self.addr_meta.var_widths):
            parts.append(byte_addr[low + width - 1, low])
            low += width
        self.bind_addr(*reversed(parts))

    def bind_addr(self, *values) -> None:
        """Drive every address region, one value per region, high region first.

        - each value is held to ITS region's width: a signal exactly that wide,
          an int that fits
        - always a combinational drive: `timing` says when the DATA moves, and
          an address is presented in the cycle it is asked
        - fires in the CALLER's scope, so a bind inside a zync takes its grant
        """
        where  = type(self).__name__
        widths = self.addr_meta.var_widths
        if len(values) != len(widths):
            raise ValueError(
                f"{where}: bind_addr needs one value per var region, got "
                f"{len(values)} for {len(widths)}")
        for region, (value, width) in enumerate(zip(values, widths)):
            check_source_width(value, width, f"{where}: bind_addr[{region}]")
            # `*=` REBINDS the name it is written on, so the source is taken
            # into a local: a port is frozen and its sources are a tuple.
            src  = self.addr_srcs[region]
            src *= value


@dataclass(frozen=True, eq=False)
class MemPortRead(MemPortBase):
    # where the value ARRIVES: the memory drives it. None is legal and means
    # another port returns the value, so there is nothing to size here.
    data : Optional[SignalRef] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.data is not None:
            check_data_width(self.data, self.addr_meta, f"{type(self).__name__}: data")

    def read(self) -> SignalRef:
        """The value this port returns, for a caller that must have one."""
        if self.data is None:
            raise ValueError(
                "MemPortRead: this port returns no data — another port returns the value")
        return self.data


@dataclass(frozen=True, eq=False)
class MemPortReadValid(MemPortRead):
    """A read port that also reports whether this cycle's answer is real.

    - a memory that always serves drives 1; one that arbitrates banks drives 0
      for the port it could not serve, and the requestor drops that answer
    - not the arbiter's job: the PipCon says whether the memory may be ASKED,
      this says whether one answer among several came back
    """
    valid : Optional[SignalRef] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.valid is None:
            raise ValueError(
                f"{type(self).__name__}: valid is required — a port of this "
                f"kind exists to report it")

    def read_valid(self) -> SignalRef:
        """The bit saying this cycle's `data` is a real answer."""
        return self.valid


@dataclass(frozen=True, eq=False)
class MemPortWrite(MemPortBase):
    data   : SignalRef                      # where the value COMES FROM
    enable : Optional[SignalRef] = None     # set when the memory routes the write

    def __post_init__(self) -> None:
        super().__post_init__()
        check_data_width(self.data, self.addr_meta, f"{type(self).__name__}: data")

    def write(self, value) -> None:
        """Drive the value, and say a write happened.

        - `enable` is what tells a memory that must ROUTE the write that this
          cycle is one: the data wire alone cannot, since it holds a value
          either way
        - fires in the CALLER's scope, so a write inside a zync takes its grant
        """
        # `|=` and `*=` REBIND the name they are written on, and a port is
        # frozen, so the handle is read into a local first.
        data = self.data
        if self.timing is PortTiming.NEXT_EDGE and self.enable is None:
            data |= value
        else:
            data *= value
        if self.enable is not None:
            enable  = self.enable
            enable *= 1
