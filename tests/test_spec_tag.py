# THE SPECULATION TAG a dispatched µop carries.
#
# A branch and everything it covers must carry ONE tag, because a squash is a
# MASK: `entry_squashed` tests `is_spec & (spec_tag & fix_tag)`, and the fix
# mask is the Mpft column of the resolving branch's own tag.
#
# Before 2026-09-15 every lane was handed `next_tag` — the tag the NEXT branch
# will allocate — so the instructions after a branch carried a tag no branch
# owned. On hello.c the branch squashed with tag 0b00010 while its wrong-path
# stores carried 0b00100, so the store buffer wrote them to memory anyway and
# `putchar` landed on the `putint` door.

from __future__ import annotations

from kathryn import Module, build_flow, flow, gen_flow, init, reset, set_top, wire

from carolyne.uarch.o3.tag_gen import TagGen
from examples.o3.rv32im.config import gen_o3_rv32im_config


def a_tag_gen(lanes: int = 2):
    """A TagGen alone in a host module, with its ports drivable."""
    cfg = gen_o3_rv32im_config(fe_lanes=lanes, commit_lanes=lanes)

    reset()

    class Host(Module):
        @init
        def declare(self):
            self.tag_gen   = TagGen(cfg, rename_ports=lanes)
            self.is_branch = [wire(1, f"is_branch{lane}") for lane in range(lanes)]
            self.booked    = {}

        @flow
        def run(self):
            # the booking builds selection nodes, so it needs a live top module
            for lane in range(lanes):
                self.booked[lane] = self.tag_gen.book_rename(lane, self.is_branch[lane])

    host = Host()
    set_top(host)
    gen_flow()
    build_flow()
    return host


def test_a_lane_does_not_carry_the_tag_the_next_branch_will_take():
    """The bug this file exists for: lane 0 used to be handed next_tag itself."""
    host = a_tag_gen()
    _is_spec, tag = host.booked[0]
    assert tag.global_id != host.tag_gen.next_tag.global_id


def test_every_lane_selects_between_what_is_open_and_what_a_branch_allocates():
    """Each lane's tag is a selection, so a branch lane and a plain one differ."""
    host = a_tag_gen()
    tags = [host.booked[lane][1].global_id for lane in range(2)]
    assert len(set(tags)) == 2                       # a per-lane answer, not one wire
    for tag_id in tags:
        assert tag_id != host.tag_gen.next_tag.global_id
        assert tag_id != host.tag_gen.free_tag.global_id


def test_the_tag_is_as_wide_as_the_machine_states():
    host  = a_tag_gen()
    width = gen_o3_rv32im_config().sptag_len
    for lane in range(2):
        assert host.booked[lane][1]._slice.stop == width


def test_the_allocator_still_hands_a_branch_the_pointer_it_consumes():
    """A branch takes `next_tag` stepped past the branches before it, so the
    pool bookkeeping (next_tag, free_tag) is unchanged by the convention."""
    host    = a_tag_gen()
    stepped = host.tag_gen._tag_after([], "probe")
    assert stepped.global_id == host.tag_gen.next_tag.global_id


