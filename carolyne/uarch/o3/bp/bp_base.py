# BpBase — the contract every branch predictor module implements.
#
#   predict(lane_pcs)     FETCH, every cycle: one BpPrediction per lane
#   on_resolve(outcome)   the BRANCH complex, when its body declares the outcome
#   on_mis_pred()         CoreO3's squash fan-out
#   on_commit(...)        TODO: the ROB carries no bp record yet, so nothing
#                         calls this
#
# Only `predict` must be written. The update hooks do nothing on the base, so a
# predictor fills in the ones it needs.
#
# A hook RESPECTS THE CALLER'S SCOPE: on_resolve runs inside the branch stage's
# pip and on_mis_pred inside the squash zif, so a write there is already gated.
#
# `may_predict_taken` is a class fact Fetch reads at elaboration: False means
# every prediction is "not taken", and Fetch builds no group cut and no
# redirect for it.

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Sequence, Tuple

from kathryn import Module

from carolyne.uarch.o3.bp.bp_spec import BpSpec

if TYPE_CHECKING:
    from carolyne.uarch.o3.config import CPUO3_Config


class BpPrediction(NamedTuple):
    """What the predictor says about ONE fetch lane."""
    taken : Any                 # 1 bit: the lane is a branch predicted taken
    npc   : Any                 # the predicted next pc, pc_width bits
    meta  : Dict[str, Any]      # one value per meta_fields name


class BpOutcome(NamedTuple):
    """How one branch really went, with the record fetch gave it."""
    pc     : Any
    taken  : Any
    target : Any
    meta   : Dict[str, Any]     # the bp record as the branch station carried it


class BpBase(Module):
    """A branch predictor: predicts at fetch, learns from the branch unit."""

    may_predict_taken = True

    def __init__(self, config: CPUO3_Config, spec: BpSpec):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config = config
        self.spec   = spec
        super().__init__()

    def predict(self, lane_pcs: Sequence) -> Tuple[BpPrediction, ...]:
        """One prediction per fetch lane, from that lane's pc.

        - called from Fetch's flow OUTSIDE its pip, so it must be
          combinational in the pc: the prediction is ready when the word is
        - `meta` holds exactly the spec's meta_fields names; Fetch stores it
          in the lane's row and the pipeline carries it to the branch station
        """
        raise NotImplementedError(
            f"{type(self).__name__}.predict: a predictor supplies this")

    def on_resolve(self, outcome: BpOutcome) -> None:
        """A branch resolved. Called in the branch stage's own scope."""

    def on_mis_pred(self) -> None:
        """The core squashes. Called inside the squash zif."""

    def on_commit(self, outcome: BpOutcome) -> None:
        """A branch retired. TODO: no caller until the ROB carries the record."""
