# ProbeBase — Carolyne's base for the MODEL half of every probe, between
# kathryn.DebugProbe and the concrete probes: what their `__init__`s share, and
# the virtual `convert` that builds the probe's SIM half from its manifest sim_reps.

from __future__ import annotations

from typing import Any, Optional

from kathryn import DebugProbe, SignalRef


class ProbeBase(DebugProbe):
    """The model half of a probe: its signals, and how its sim half is built."""

    def set_if_bound(self, name: str, value: Optional[Any]) -> None:
        if value is not None:                       # None: no manifest child, not a None attribute
            setattr(self, name, value)          # a signal, a table, or a Module the class may not have

    def convert(self, sim_reps: Any) -> Any:
        """Build this probe's sim half from `sim_reps`, its manifest node (`k.<attr>`).
        - the implementation names every field it reads; optional children go
          through `child_or_none`, so a signal the model did not expose reads None.
        - called on the MODEL probe, so a cocotb test rebuilds the model in the
          simulator process to have the instance (no emit there).
        """
        raise NotImplementedError(f"{type(self).__name__}.convert: the probe states how its sim_reps is read")
