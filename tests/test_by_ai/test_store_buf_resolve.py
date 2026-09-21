# THE STORE BUFFER'S RESOLVE: a guard may not read the wire its own write drives.
#
# `spec_overrider` carries the pair of the store being pushed this cycle, so a
# prediction resolving in that cycle can be masked out of it before the row
# write reads it. Guarding that write on the overrider ITSELF is a
# combinational loop: the write clears the bits the guard reads, the guard then
# stops holding, and the value oscillates.
#
# It only bites when a resolve really matches. Once the speculation tag a µop
# carries was corrected (2026-09-15) the match started happening and Verilator
# refused the design: "Active region did not converge". The exec complex's own
# on_suc_pred documents the same trap; this is the store buffer learning it.

from __future__ import annotations

import inspect

from kathryn import build_model, reset
from kathryn.signal import to_ref

from carolyne.uarch.o3.store_buf import StoreBuf
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config


def test_the_resolve_guard_reads_what_the_caller_stated():
    source = inspect.getsource(StoreBuf.on_suc_pred)
    assert "stated_spec" in source, "the guard must read the stated pair, not the overrider"


def test_no_guard_in_the_resolve_reads_the_overrider():
    source = inspect.getsource(StoreBuf.on_suc_pred)
    guards = [line for line in source.splitlines()
              if "zif(" in line or line.strip().startswith("&")]
    assert guards, "the resolve has a guard"
    assert not any("spec_overrider" in line for line in guards), \
        f"a guard reads the wire the write drives: {guards}"


def test_the_push_states_the_pair_once_on_the_source_wire():
    """on_new_entry drives the SOURCE only; the overrider is a stated copy of
    it, so the two cannot drift and the relationship is written down once."""
    push = inspect.getsource(StoreBuf.on_new_entry)
    assert "self.stated_spec[0] *=" in push
    assert "self.spec_overrider[0] *=" not in push          # it is not driven here
    copy = inspect.getsource(StoreBuf.run_spec_overrider)
    assert "self.spec_overrider[0] *= self.stated_spec[0]" in copy


def test_the_copy_is_the_robs_own_flow_and_loses_to_the_resolve():
    """The copy runs plain, so on_suc_pred's PRI_SUC_PRED override beats it —
    priority IS emission order, and the mask must be emitted after the copy."""
    assert getattr(StoreBuf.run_spec_overrider, "_kathryn_phase", None) == "flow"
    copy = inspect.getsource(StoreBuf.run_spec_overrider)
    assert "priority" not in copy and "zif" not in copy


def test_both_lanes_exist_and_are_the_machines_tag_wide():
    reset()
    st_buf = build_model(build_machine(gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2))).core.store_buf
    width  = gen_o3_rv32im_config().sptag_len
    for lane in (st_buf.stated_spec, st_buf.spec_overrider):
        assert to_ref(lane[0].spec_tag)._slice.stop == width
