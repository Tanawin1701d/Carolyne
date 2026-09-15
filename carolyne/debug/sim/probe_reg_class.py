# The register-class probe: the Arf, Prf and Rt of ONE class, which live behind
# RegArchMng (not a Module) and would otherwise never reach the manifest.
# - RegClassProbe    (model side, a ProbeBase): the three blocks, `prf`/`rt`
#   only when the class is renamed.
# - RegClassSimProbe (sim side): the same three as KSim module views; built by
#   `RegClassProbe.convert(sim_reps)`.

from __future__ import annotations

from typing import Any, Optional

from .probe_base     import ProbeBase
from .probe_sim_util import child_or_none


# ---- model side ---------------------------------------------------------------

class RegClassProbe(ProbeBase):
    """One register class's blocks, for the sim manifest."""

    def __init__(
        self,
        arf : Any,
        prf : Optional[Any] = None,
        rt  : Optional[Any] = None,
    ) -> None:
        self.arf = arf
        self.set_if_bound("prf", prf)
        self.set_if_bound("rt",  rt)

    def convert(self, sim_reps: Any) -> "RegClassSimProbe":
        return RegClassSimProbe(
            arf = sim_reps.arf,
            prf = child_or_none(sim_reps, "prf"),
            rt  = child_or_none(sim_reps, "rt"),
        )


# ---- sim side -----------------------------------------------------------------

class RegClassSimProbe:
    """One register class's blocks as KSim module views: their probes read under them."""

    def __init__(
        self,
        arf : Any,
        prf : Optional[Any] = None,
        rt  : Optional[Any] = None,
    ) -> None:
        self.arf = arf
        self.prf = prf
        self.rt  = rt

    @property
    def is_renamed(self) -> bool: return self.prf is not None
