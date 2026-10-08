# The predictors a machine can be built with, by NAME: a config knob must be a
# plain string and int, because the knobs cross to the simulator process as JSON.

from __future__ import annotations

from carolyne.uarch.o3.bp.bp_btb_bimodal  import BtbBimodalSpec
from carolyne.uarch.o3.bp.bp_fall_through import FallThroughSpec
from carolyne.uarch.o3.bp.bp_spec         import BpSpec

BP_FALL_THROUGH = "fall_through"
BP_BTB          = "btb"
BP_NAMES        = (BP_FALL_THROUGH, BP_BTB)


def bp_spec_named(bp: str, bp_entries: int = 32) -> BpSpec:
    """The spec a knob names. `bp_entries` sizes the BTB and is ignored otherwise."""
    if bp == BP_FALL_THROUGH:
        return FallThroughSpec()
    if bp == BP_BTB:
        return BtbBimodalSpec(entries=bp_entries)
    raise ValueError(f"no branch predictor named {bp!r}: one of {BP_NAMES}")
