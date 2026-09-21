# The snapshot-vs-commit collision: a branch that checkpoints in the very
# cycle a mapping retires must not record the dropped mapping — restoring it
# later resurrects a rename whose register has been freed and recycled, and
# every later reader waits for a writeback that already happened. The drop
# is on the commit row, the head of the chain, so the snapshot copy is a
# plain copy and the ladder has no rung for it. Pinned by structure (the
# test_rt_commit idiom).

from __future__ import annotations

import inspect

import carolyne.uarch.o3.priority as priority_mod
import carolyne.uarch.o3.rt as rt_mod
from carolyne.uarch.o3.priority import PRI_COMMIT, PRI_MIS_PRED, PRI_RENAME
from carolyne.uarch.o3.rt import Rt


def test_the_ladder_has_no_snapshot_rung():
    assert PRI_COMMIT < PRI_RENAME < PRI_MIS_PRED
    assert not hasattr(priority_mod, "PRI_SNAPSHOT_FIX")


def test_the_snapshot_is_a_plain_copy_of_the_chain():
    """Nothing corrects the snapshot: the chain it copies already has this
    cycle's commits dropped (on_commit writes the commit row)."""
    source = inspect.getsource(Rt.on_rename)
    assert "copy_row(self.spec_rt[OH(spectag_dyn)]" in source
    assert not hasattr(rt_mod, "copy_row_dropping")
    assert not hasattr(Rt, "commit_drops")


def test_the_drop_is_on_the_head_of_the_chain():
    """temp_commit feeds temp_dispatch[0], which feeds every later row: one
    write reaches every rename port, every snapshot and master."""
    flow = inspect.getsource(Rt.on_normal_flow)
    assert "copy_row(self.temp_dispatch[0], self.temp_commit[0]" in flow
    commit = inspect.getsource(Rt.on_commit)
    assert "write_entry(self.temp_commit[0]" in commit
