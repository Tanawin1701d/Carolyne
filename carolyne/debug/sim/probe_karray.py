# The Karray-table probe, in two explicit halves:
# - KarrayProbe    (model side, a ProbeBase): the table and, when the
#   block has them, the head pointer and the used count that bound its live rows.
# - KarraySimProbe (sim side): the same three as KSim objects, plus row reading;
#   built by `KarrayProbe.convert(sim_reps)`.
# - LIMIT: rows() reads a ONE-dimensional table (the ROB, a station, the store
#   buffer). A 2-D table is read one plane at a time, through `plane(idx)`.

from __future__ import annotations

from typing import Any, Dict, List, Optional

from kathryn import Karray, SignalRef

from .probe_base     import ProbeBase
from .probe_sim_util import child_or_none, read_value


# ---- model side ---------------------------------------------------------------

class KarrayProbe(ProbeBase):
    """One table, and the pointers that bound its live rows, for the sim manifest."""

    def __init__(
        self,
        table : Karray,
        head  : Optional[SignalRef] = None,
        count : Optional[SignalRef] = None,
    ) -> None:
        self.table = table
        self.set_if_bound("head",  head)
        self.set_if_bound("count", count)

    def convert(self, sim_reps: Any) -> "KarraySimProbe":
        return KarraySimProbe(
            table = sim_reps.table,
            head  = child_or_none(sim_reps, "head"),
            count = child_or_none(sim_reps, "count"),
        )


# ---- sim side -----------------------------------------------------------------

class KarraySimProbe:
    """One table's rows at sim time, and the pointers that bound the live ones."""

    def __init__(
        self,
        table : Any,
        head  : Optional[Any] = None,
        count : Optional[Any] = None,
    ) -> None:
        self.table = table
        self.head  = head
        self.count = count

    def __len__(self) -> int:       return len(self.table)
    def fields (self) -> List[str]: return list(dir(self.table[0]))    # the table's own field names

    def plane(self, index: int) -> "KarraySimProbe":
        """One plane of a 2-D table, as a probe over its rows (a rename table's master plane)."""
        return KarraySimProbe(self.table[index])

    def row(self, idx: int) -> Dict[str, Optional[int]]:
        elem = self.table[idx]
        return {name: read_value(getattr(elem, name)) for name in self.fields()}   # None: X, never written

    def rows(self) -> List[Dict[str, Optional[int]]]:
        return [self.row(idx) for idx in range(len(self))]

    def live_rows(self, valid: Optional[str] = None) -> List[int]:
        """Row indices in use: those with `valid` set, else the head+count window, else all."""
        if valid is not None:
            return [idx for idx in range(len(self)) if read_value(getattr(self.table[idx], valid)) == 1]
        if self.head is not None and self.count is not None:
            start, used = read_value(self.head), read_value(self.count)
            return [(start + step) % len(self) for step in range(used)]
        return list(range(len(self)))
