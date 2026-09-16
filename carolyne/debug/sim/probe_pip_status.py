# The pipeline-status probe of ONE PipCon, in two explicit halves:
# - PipStatusProbe    (model side, a ProbeBase): stores the signals a
#   `@dbg` body reads off the PipCon; only the ones that exist become attributes.
# - PipStatusSimProbe (sim side): the same signals as cocotb handles, named one
#   by one, plus the status words; built by `PipStatusProbe.convert(sim_reps)`.
# - `mack` is the pip's entrance sim_reps and the body is entered on `mack & mreq`;
#   the pip's OWN leaf is not the entrance (undriven unless `auto_req`).
# - LIMIT: a signal resolves in the scope of the MODULE HOLDING the probe, and a
#   leaf's wires are declared by the module that ZYNCS on the arb, a flush wire
#   by the module that calls flush(). Such a signal reads UNRESOLVED here and the
#   status words say UNKNOWN rather than guessing (docs/open_items.md).

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from kathryn import PipCon

from .probe_base     import ProbeBase
from .probe_sim_util import child_or_none, read_value

# ---- status words -------------------------------------------------------------
RUNNING = "RUNNING"     # the entrance fired with a request: the body runs
IDLE    = "IDLE"        # parked (wait4syn high), or the entrance fired and nobody asks
HELD    = "HELD"        # somebody asks but the entrance did not fire (hold, or a busy body)
BUSY    = "BUSY"        # nobody asks and the entrance did not fire: inside its body
STALL   = "STALL"       # stage: held by its own arbiter's hold, or the next arbiter did not take its output
FLUSH   = "FLUSH"       # stage: its own arbiter's reset is high
UNKNOWN = "UNKNOWN"     # a signal the word needs did not resolve in this module's scope

GRANTED = "GRANTED"     # leaf: req and ack (an auto_ack leaf's ack is a constant: no req, no grant)
WAITING = "WAITING"     # leaf: req and no ack
QUIET   = "QUIET"       # leaf: no req


# Every signal this probe may store beside `mreq`, which every arb has.
PIP_STATUS_SIGNALS = ("mack", "hold", "reset", "pip_req", "pip_ack", "pip_wait",
                      "leaf_req", "leaf_ack")


# ---- model side ---------------------------------------------------------------

class PipStatusProbe(ProbeBase):
    """One PipCon's status signals, stored for the sim manifest."""

    def __init__(self, con: PipCon) -> None:
        self.mreq = con.master_req
        self.set_if_bound("mack",  con.master_ack)
        self.set_if_bound("hold",  con.hold)
        self.set_if_bound("reset", con.reset)
        pip_leaf = con.pip_leaf
        if pip_leaf is not None:
            self.pip_req  = pip_leaf.req
            self.pip_ack  = pip_leaf.ack
            self.pip_wait = con.pip_wait_reg
        self.leaf_req = [con.leaf(idx).req for idx in range(con.leaf_count)]
        self.leaf_ack = [con.leaf(idx).ack for idx in range(con.leaf_count)]

    def convert(self, sim_reps: Any) -> "PipStatusSimProbe":
        # Every child goes through child_or_none, the leaf lists included: a
        # leaf is declared by the module that zyncs on this arb, so it may not
        # resolve here. `unresolved` is what this probe stored and the manifest
        # could not reach, which is what tells a missing signal from an absent one.
        found = {name: child_or_none(sim_reps, name) for name in PIP_STATUS_SIGNALS}
        return PipStatusSimProbe(
            mreq       = sim_reps.mreq,
            leaf_req   = found["leaf_req"],
            leaf_ack   = found["leaf_ack"],
            mack       = found["mack"],
            hold       = found["hold"],
            reset      = found["reset"],
            pip_req    = found["pip_req"],
            pip_ack    = found["pip_ack"],
            pip_wait   = found["pip_wait"],
            unresolved = tuple(name for name in PIP_STATUS_SIGNALS
                               if hasattr(self, name) and found[name] is None),
        )


# ---- sim side -----------------------------------------------------------------

class PipStatusSimProbe:
    """The same signals as cocotb handles, and the status words read off them."""

    def __init__(
        self,
        mreq       : Any,
        leaf_req   : Optional[List[Any]] = None,
        leaf_ack   : Optional[List[Any]] = None,
        mack       : Optional[Any] = None,
        hold       : Optional[Any] = None,
        reset      : Optional[Any] = None,
        pip_req    : Optional[Any] = None,
        pip_ack    : Optional[Any] = None,
        pip_wait   : Optional[Any] = None,
        unresolved : Tuple[str, ...] = (),
    ) -> None:
        self.mreq       = mreq
        self.leaf_req   = leaf_req
        self.leaf_ack   = leaf_ack
        self.mack       = mack
        self.hold       = hold
        self.reset      = reset
        self.pip_req    = pip_req
        self.pip_ack    = pip_ack
        self.pip_wait   = pip_wait
        self.unresolved = unresolved       # stored by the model, out of this module's scope

    def bit(self, handle: Optional[Any]) -> Optional[int]:
        return None if handle is None else read_value(handle)

    def lost(self, *names: str) -> bool:
        """True when any named signal was stored but did not resolve here."""
        return any(name in self.unresolved for name in names)

    @property
    def has_pip   (self) -> bool:          return self.pip_wait is not None
    @property
    def leaf_count(self) -> int:           return 0 if self.leaf_req is None else len(self.leaf_req)
    @property
    def parked    (self) -> Optional[int]: return self.bit(self.pip_wait)     # wait4syn: nobody asked when entered

    def leaf(self, idx: int) -> Tuple[Optional[int], Optional[int]]:
        if self.leaf_req is None or self.leaf_ack is None:
            return (None, None)
        return (read_value(self.leaf_req[idx]), read_value(self.leaf_ack[idx]))

    def pip_status(self) -> str:
        """RUNNING / IDLE / HELD / BUSY, from the pip's own arbiter alone.
        - wait4syn high is IDLE whatever else reads: an entry taken now runs after the edge.
        """
        if not self.has_pip:
            raise ValueError("pip_status: no pip masters this PipCon")
        if self.parked:   return IDLE
        mreq, mack = self.bit(self.mreq), self.bit(self.mack)
        if mack and mreq: return RUNNING
        if mack:          return IDLE
        if mreq:          return HELD
        return BUSY

    def leaf_status(self, idx: int) -> str:
        """GRANTED / WAITING / QUIET for one leaf, UNKNOWN when it is out of scope."""
        if self.lost("leaf_req", "leaf_ack"):
            return UNKNOWN
        req, ack = self.leaf(idx)
        if req and ack: return GRANTED
        if req:         return WAITING      # not ack but there is request
        return QUIET

    def stage_status(self, next_probe: "PipStatusSimProbe", next_leaf_idx: int) -> str:
        """IDLE / STALL / FLUSH / RUNNING: this stage's own arbiter gates first, then its hop to the next."""
        if self.parked:
            return IDLE
        # the system is not park (wait node is not set), it mean it is doing something
        if self.lost("hold", "reset"):                        return UNKNOWN
        if self.bit(self.hold):                               return STALL
        if self.bit(self.reset):                              return FLUSH
        hop = next_probe.leaf_status(next_leaf_idx)
        if hop == UNKNOWN:                                    return UNKNOWN
        if hop != GRANTED:                                    return STALL
        return RUNNING
