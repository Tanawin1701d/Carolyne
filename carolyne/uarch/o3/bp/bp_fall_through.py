# Fall-through — the predictor that always says "not taken": every lane's next
# pc is its own pc + ilen_bytes. It keeps no state and carries no record, so
# the pipeline is the same as a core built with no predictor at all.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence, Tuple

from kathryn import val

from carolyne.uarch.o3.bp.bp_base import BpBase, BpPrediction
from carolyne.uarch.o3.bp.bp_spec import BpSpec

if TYPE_CHECKING:
    from carolyne.uarch.o3.config import CPUO3_Config


@dataclass(frozen=True)
class FallThroughSpec(BpSpec):

    def meta_fields(self, config: CPUO3_Config) -> tuple:  return ()
    def build      (self, config: CPUO3_Config) -> BpBase: return FallThroughBp(config, self)


class FallThroughBp(BpBase):
    """Never taken: next pc = pc + ilen_bytes."""

    may_predict_taken = False

    def predict(self, lane_pcs: Sequence) -> Tuple[BpPrediction, ...]:
        ilen = self.config.isa.ilen_bytes
        return tuple(BpPrediction(val(1, 0), pc + ilen, {}) for pc in lane_pcs)
