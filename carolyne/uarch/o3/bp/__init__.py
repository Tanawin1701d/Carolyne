# The branch predictor subsystem of the O3 core.
#
#   bp_spec.py          BpSpec — the config names one (CPUO3_Config.bp_spec)
#   bp_base.py          BpBase — the module contract; BpPrediction, BpOutcome
#   bp_helper.py        the bp record every pipeline record carries
#   bp_fall_through.py  FallThroughSpec / FallThroughBp: never taken
#   bp_btb_bimodal.py   BtbBimodalSpec / BtbBimodalBp: a BTB with a 2-bit counter per entry
#   bp_catalog.py       bp_spec_named: a predictor by name, for a JSON config knob

from carolyne.uarch.o3.bp.bp_spec         import BP_FIELD_PREFIX, BpSpec
from carolyne.uarch.o3.bp.bp_base         import BpBase, BpOutcome, BpPrediction
from carolyne.uarch.o3.bp.bp_fall_through import FallThroughBp, FallThroughSpec
from carolyne.uarch.o3.bp.bp_btb_bimodal  import BtbBimodalBp, BtbBimodalSpec
from carolyne.uarch.o3.bp.bp_catalog      import BP_BTB, BP_FALL_THROUGH, BP_NAMES, bp_spec_named
