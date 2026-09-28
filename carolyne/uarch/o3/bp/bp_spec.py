# BpSpec — the config-side description of a branch predictor: which one the
# machine builds, and the per-branch record it needs carried down the pipeline.
#
# Frozen data like RsvSpec, and free of Kathryn: CPUO3_Config holds one and
# checks it at construction. The predictor MODULE comes from `build`, called
# inside CoreO3's @init.
#
#   meta_fields(config)   (name, width) pairs of the bp record (BHR, PHT index)
#                         that go fetch -> decode -> dispatch -> branch station
#   build(config)         the BpBase module this spec describes
#
# Every name in the record starts with BP_FIELD_PREFIX, so a predictor's field
# can never take the name of a field the engine already has (bp_helper checks).

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from carolyne.uarch.o3.bp.bp_base import BpBase
    from carolyne.uarch.o3.config import CPUO3_Config

BP_FIELD_PREFIX = "bp_"


@dataclass(frozen=True)
class BpSpec:
    """One branch predictor kind. A subclass states its knobs as fields."""

    def meta_fields(self, config: CPUO3_Config) -> Tuple[Tuple[str, int], ...]:
        """The (name, width) pairs of the per-branch record this predictor needs.

        - each name starts with BP_FIELD_PREFIX
        - the record is written at fetch and read back at resolve
          (BpOutcome.meta), so it holds what the update needs to find its
          own state again
        - () is legal: a predictor with no state carries nothing
        """
        raise NotImplementedError(
            f"{type(self).__name__}.meta_fields: a predictor spec states its record")

    def build(self, config: CPUO3_Config) -> BpBase:
        """The predictor module. Declares hardware: call it inside an open
        Kathryn module scope (CoreO3's @init)."""
        raise NotImplementedError(
            f"{type(self).__name__}.build: a predictor spec builds its module")

    @property
    def label(self) -> str:
        """The predictor named by its spec class, for messages."""
        return type(self).__name__
