# The branch-resolution probe: what an execution complex DECLARED — the
# mispredict condition, the pc it redirects to, and the correct-prediction
# condition.
#
# These signals are built inside the declaring complex's own stage scope, so
# they resolve there and nowhere else. That is why the probe is the complex's:
# an arbiter's flush wire is declared by whoever calls flush(), which for every
# arb in the core is this one complex (probe_pip_status.py's LIMIT).
#
# A complex that declares no resolution stores None for all three, and the
# sim half answers None.

from __future__ import annotations

from typing import Any, Optional

from .probe_base     import ProbeBase
from .probe_sim_util import child_or_none, read_value


# ---- model side ---------------------------------------------------------------

class BranchResolveProbe(ProbeBase):
    """One complex's declared resolution, for the sim manifest."""

    def __init__(
        self,
        mis_pred    : Optional[Any] = None,
        redirect_pc : Optional[Any] = None,
        suc_pred    : Optional[Any] = None,
    ) -> None:
        self.set_if_bound("mis_pred",    mis_pred)
        self.set_if_bound("redirect_pc", redirect_pc)
        self.set_if_bound("suc_pred",    suc_pred)

    def convert(self, sim_reps: Any) -> "BranchResolveSimProbe":
        return BranchResolveSimProbe(
            mis_pred    = child_or_none(sim_reps, "mis_pred"),
            redirect_pc = child_or_none(sim_reps, "redirect_pc"),
            suc_pred    = child_or_none(sim_reps, "suc_pred"),
        )


# ---- sim side -----------------------------------------------------------------

class BranchResolveSimProbe:
    """The declared resolution at sim time."""

    def __init__(
        self,
        mis_pred    : Optional[Any] = None,
        redirect_pc : Optional[Any] = None,
        suc_pred    : Optional[Any] = None,
    ) -> None:
        self.mis_pred    = mis_pred
        self.redirect_pc = redirect_pc
        self.suc_pred    = suc_pred

    @property
    def declares(self) -> bool: return self.mis_pred is not None

    def read_mis_pred   (self) -> Optional[int]: return None if self.mis_pred    is None else read_value(self.mis_pred)
    def read_suc_pred   (self) -> Optional[int]: return None if self.suc_pred    is None else read_value(self.suc_pred)
    def read_redirect_pc(self) -> Optional[int]: return None if self.redirect_pc is None else read_value(self.redirect_pc)
