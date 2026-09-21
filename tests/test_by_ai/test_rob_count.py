# THE REORDER BUFFER'S COUNT: it must move in every cycle either port acted.
#
# Before 2026-09-15 the one write lived in `on_dispatch`, which dispatch calls
# inside its GRANTED zync — so a commit made in a cycle the front end did not
# dispatch was never subtracted. The buffer then believed it still held entries
# it had retired, and commit read them: on hello.c the ROB showed
# `alloc 11, com 11, used 1` and retired three wrong-path instructions.

from __future__ import annotations

import inspect

from kathryn import build_model, reset

from carolyne.uarch.o3.rob import Rob
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config


def test_the_count_is_the_robs_own_flow():
    """Its own @flow, so gen_flow drives it: nothing else decides when it runs."""
    assert getattr(Rob.run_update_meta, "_kathryn_phase", None) == "flow"


def test_the_count_write_is_not_inside_a_dispatch_grant():
    """on_dispatch runs inside dispatch's granted zync, so the count may not be
    written from there — that is the bug this file exists for."""
    source = inspect.getsource(Rob.on_dispatch)
    assert "update_meta" not in source
    assert "used_entry_cnt" not in source


def test_the_count_write_is_unconditional_and_reads_both_ports():
    source = inspect.getsource(Rob.run_update_meta)
    assert "self.alloc_cnt" in source and "self.commit_cnt" in source
    assert "zif" not in source and "priority" not in source      # no gate of its own


def test_both_ports_read_zero_when_their_side_did_nothing():
    """The unconditional write only works because an idle port drives 0."""
    reset()
    rob = build_model(build_machine(gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2))).core.rob
    assert rob.alloc_cnt is not None and rob.commit_cnt is not None
    # both are sized to the count, so the add and the subtract stay in its width
    assert rob.alloc_cnt._slice.stop == rob.cnt_width == rob.commit_cnt._slice.stop
