# The branch predictor contract (uarch/o3/bp/): a config names one, fetch asks
# it, and its per-branch record goes to the branch station and comes back at
# resolve.
#
# FallThroughSpec carries no record and never says taken, so it builds neither
# the transport nor fetch's group cut. `ProbeBpSpec` below is test-only and
# does both, so the paths a real predictor will use elaborate today.

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pytest
from kathryn import build_model, init, reg, reset

from carolyne.uarch.o3.bp import (BpBase, BpOutcome, BpPrediction, BpSpec,
                                  FallThroughBp, FallThroughSpec)
from carolyne.uarch.o3.bp.bp_helper import bp_field_widths
from carolyne.uarch.o3.config import RsvType
from carolyne.uarch.o3.decode_helper import decode_entry_shape
from carolyne.uarch.o3.dispatch_helper import dispatch_field_names
from carolyne.uarch.o3.fetch_helper import fetch_entry_shape
from carolyne.uarch.o3.rsv_helper import rsv_field_names
from examples.o3.core.build import build_machine
from examples.o3.mips32.config import gen_o3_mips32_config
from examples.o3.rv32im.config import gen_o3_rv32im_config

HIST_BITS = 4


class ProbeBp(BpBase):
    """Says taken on every pc with bit 2 set; keeps a history register."""

    @init
    def com_declare(self):
        self.hist      = reg(HIST_BITS, "bp_probe_hist")
        self.outcomes  = []         # what on_resolve was handed, per call
        self.mis_preds = 0

    def predict(self, lane_pcs):
        return tuple(BpPrediction(pc[2, 2], pc + 8, {"bp_hist": self.hist})
                     for pc in lane_pcs)

    def on_resolve(self, outcome):
        self.outcomes.append(outcome)
        self.hist |= (self.hist << 1) | outcome.taken

    def on_mis_pred(self):
        self.mis_preds += 1


@dataclass(frozen=True)
class ProbeBpSpec(BpSpec):
    meta: tuple = (("bp_hist", HIST_BITS),)

    def meta_fields(self, config): return self.meta
    def build      (self, config): return ProbeBp(config, self)


def probe_config(**bp_knobs):
    return dataclasses.replace(gen_o3_rv32im_config(), bp_spec=ProbeBpSpec(**bp_knobs))


# ---- the config ---------------------------------------------------------------

def test_the_config_requires_a_predictor_spec():
    with pytest.raises(TypeError, match="bp_spec must be a BpSpec"):
        dataclasses.replace(gen_o3_rv32im_config(), bp_spec=None)


def test_both_example_machines_use_fall_through():
    assert isinstance(gen_o3_rv32im_config().bp_spec, FallThroughSpec)
    assert isinstance(gen_o3_mips32_config().bp_spec, FallThroughSpec)


@pytest.mark.parametrize("meta, message", [
    ((("hist", 4),),                       "must start with 'bp_'"),
    ((("bp_hist", 0),),                    "width >= 1"),
    ((("bp_hist", 4), ("bp_hist", 2)),     "two fields"),
    ((("bp hist", 4),),                    "not an identifier"),
])
def test_a_bad_record_is_refused(meta, message):
    with pytest.raises(ValueError, match=message):
        bp_field_widths(probe_config(meta=meta))


# ---- the record's path --------------------------------------------------------

def test_fall_through_adds_no_record_field():
    config = gen_o3_rv32im_config()
    assert bp_field_widths(config) == {}
    assert not any(name.startswith("bp_") for name in dispatch_field_names(config))


def test_the_record_goes_fetch_decode_dispatch_and_only_the_branch_station():
    config = probe_config()
    assert fetch_entry_shape (config)[1]["bp_hist"].width == HIST_BITS
    assert decode_entry_shape(config)[1]["bp_hist"].width == HIST_BITS
    assert "bp_hist" in dispatch_field_names(config)
    for spec in config.rsv_specs:
        carried = "bp_hist" in rsv_field_names(config, spec)
        assert carried == (spec.rsv_type is RsvType.RSV_BRANCH), spec.label


def test_fetch_carries_the_predicted_npc():
    assert "npc" in fetch_entry_shape(gen_o3_rv32im_config())[1]


# ---- elaboration --------------------------------------------------------------

@pytest.mark.parametrize("gen_config", [gen_o3_rv32im_config, gen_o3_mips32_config])
def test_fall_through_elaborates_on_both_isas(gen_config):
    reset()
    machine = build_model(build_machine(gen_config()), debug=True)
    assert isinstance(machine.core.bp, FallThroughBp)


def test_a_predictor_that_says_taken_elaborates_and_learns_every_branch():
    # the fetch group cut, the redirect mux, the record through every stage,
    # and the outcome back from the branch body — one elaboration
    reset()
    machine = build_model(build_machine(probe_config()), debug=True)
    bp      = machine.core.bp
    assert len(bp.outcomes) == 1                 # one branch complex declares
    outcome = bp.outcomes[0]
    assert isinstance(outcome, BpOutcome)
    assert set(outcome.meta) == {"bp_hist"}
    assert bp.mis_preds == 1                     # the squash fan-out calls it


def test_fetch_refuses_a_prediction_whose_record_differs_from_the_spec():
    class WrongMetaBp(ProbeBp):
        def predict(self, lane_pcs):
            return tuple(BpPrediction(pc[2, 2], pc + 8, {}) for pc in lane_pcs)

    @dataclass(frozen=True)
    class WrongMetaSpec(ProbeBpSpec):
        def build(self, config): return WrongMetaBp(config, self)

    reset()
    config = dataclasses.replace(gen_o3_rv32im_config(), bp_spec=WrongMetaSpec())
    with pytest.raises(ValueError, match="the spec declares"):
        build_model(build_machine(config), debug=True)
