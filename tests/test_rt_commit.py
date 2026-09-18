# THE RENAME TABLE'S COMMIT: a mapping that retires must be DROPPED.
#
# Before 2026-09-15 `renamed` was set by on_rename and cleared NOWHERE. Commit
# wrote the physical index back over itself, and the loop meant to repair the
# speculative planes indexed plane 0 every time instead of the loop variable.
# So every architectural register stayed marked renamed forever: once the
# physical pool wrapped and reallocated that register, a reader waited on a
# writeback that was not coming. On hello.c the `ret` at the end of main sat in
# the branch station waiting on its return address for the rest of the run.

from __future__ import annotations

import ast
import inspect

from kathryn import build_model, reset

from carolyne.uarch.o3.rt import Rt
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config


def commit_source() -> str:
    return inspect.getsource(Rt.on_commit)


def test_commit_clears_the_rename():
    assert "RENAMED: 0" in commit_source() or "renamed=0" in commit_source()


def test_commit_does_not_write_the_physical_index_back_over_itself():
    """The old body's only effect: prf_idx = prf_idx, leaving `renamed` set."""
    assert "prf_idx=prf_dyn_idx" not in commit_source()


def test_every_speculative_plane_is_repaired_not_plane_zero_five_times():
    """The loop variable must index the plane, or four of the five snapshots
    keep a mapping that has since committed and a later squash restores it."""
    tree  = ast.parse(inspect.getsource(Rt.on_commit).lstrip())
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
    assert loops, "the repair walks the planes"
    var  = loops[0].target.id
    subs = [n for n in ast.walk(loops[0])
            if isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Attribute) and n.value.attr == "spec_rt"]
    assert subs, "the loop reaches spec_rt"
    for sub in subs:
        assert isinstance(sub.slice, ast.Name) and sub.slice.id == var, \
            "a spec_rt plane is indexed by a constant inside the loop"


def test_the_clear_is_clocked_and_not_put_on_the_row_readers_see():
    """The Arf takes the value at the edge, so a reader in the commit cycle must
    still see the rename and read the physical register. Clearing the bit on
    temp_commit, which read_rename reads, hands that reader a stale value."""
    source = commit_source()
    assert "self.master_rt[0][arch_dyn_idx] |=" in source
    assert "temp_commit" not in source


def test_the_guard_reads_what_the_rename_chain_will_write():
    """A lane renaming the same register this cycle leaves a different physical
    index there, and that younger mapping must stand."""
    assert "temp_dispatch[self.rename_ports - 1]" in commit_source()


def test_the_table_still_elaborates_in_the_whole_machine():
    reset()
    core = build_model(build_machine(gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)),
                       debug=True).core
    rt = core.dbg_reg_arch["x"].rt
    assert rt.master_rt is not None and rt.spec_rt is not None
