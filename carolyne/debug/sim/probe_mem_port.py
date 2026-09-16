# The memory-port probe: the WIRES of one access — the index it names, its
# bank, the data it carries and the bit that says an access happened. The
# port's ARBITER is PipStatusProbe's; this is what moves through the port.
#
# - MemPortProbe    (model side, a ProbeBase): the signals, handed in by the
#   memory. It imports no uarch, so `carolyne.debug.sim` stays importable by
#   mem_base.py.
# - MemPortSimProbe (sim side): the same signals as cocotb handles, plus
#   `write_access()`, which reads `enable` FIRST and the rest only when set.
# - A read port's `valid` is the memory's bank-conflict answer, NOT "an access
#   happened" — that is the port arbiter's grant.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from kathryn import SignalRef

from .probe_base     import ProbeBase
from .probe_sim_util import child_or_none, read_value


@dataclass(frozen=True)
class MemAccess:
    """One access a port made: where it landed and what it carried."""
    index : Optional[int]
    bank  : Optional[int]
    data  : Optional[int]


# ---- model side ---------------------------------------------------------------

class MemPortProbe(ProbeBase):
    """One memory port's address, data and gate signals, for the sim manifest."""

    def __init__(
        self,
        index  : SignalRef,
        data   : Optional[SignalRef] = None,
        bank   : Optional[SignalRef] = None,
        enable : Optional[SignalRef] = None,
        valid  : Optional[SignalRef] = None,
    ) -> None:
        self.index = index
        self.set_if_bound("data",   data)       # a read port may return no data
        self.set_if_bound("bank",   bank)       # only a banked memory has one
        self.set_if_bound("enable", enable)     # writes only
        self.set_if_bound("valid",  valid)      # reads that report a conflict

    def convert(self, sim_reps: Any) -> "MemPortSimProbe":
        return MemPortSimProbe(
            index  = sim_reps.index,
            data   = child_or_none(sim_reps, "data"),
            bank   = child_or_none(sim_reps, "bank"),
            enable = child_or_none(sim_reps, "enable"),
            valid  = child_or_none(sim_reps, "valid"),
        )


# ---- sim side -----------------------------------------------------------------

class MemPortSimProbe:
    """One memory port's wires at sim time; a write is read gate first."""

    def __init__(
        self,
        index  : Any,
        data   : Optional[Any] = None,
        bank   : Optional[Any] = None,
        enable : Optional[Any] = None,
        valid  : Optional[Any] = None,
    ) -> None:
        self.index  = index
        self.data   = data
        self.bank   = bank
        self.enable = enable
        self.valid  = valid

    @property
    def is_write(self) -> bool: return self.enable is not None

    def read_index (self) -> Optional[int]: return read_value(self.index)
    def read_bank  (self) -> Optional[int]: return None if self.bank   is None else read_value(self.bank)
    def read_data  (self) -> Optional[int]: return None if self.data   is None else read_value(self.data)
    def read_enable(self) -> Optional[int]: return None if self.enable is None else read_value(self.enable)
    def read_valid (self) -> Optional[int]: return None if self.valid  is None else read_value(self.valid)

    def write_access(self) -> Optional[MemAccess]:
        """The write this cycle, or None when the port wrote nothing.

        - `enable` is read FIRST and the address and data only after it: the
          data wire holds a value either way, so the gate is what says a write
          happened, and a cycle with no write costs one handle read
        """
        if not self.is_write:
            raise ValueError(
                "MemPortSimProbe.write_access: this port has no enable — "
                "a read port reports its access through its arbiter's grant")
        if self.read_enable() != 1:
            return None
        return MemAccess(index = self.read_index(),
                         bank  = self.read_bank(),
                         data  = self.read_data())
