# FETCH MUST WAIT FOR EVERY ARBITER, not just one.
#
# Fetch zyncs on a LIST of arbiters: decode's, and one per instruction memory
# port. Kathryn's default `mode="any"` ORs their grants, so the memory
# answering was enough to capture a new group whether or not decode had taken
# the previous one — and fetch overwrote its own unread record.
#
# MEASURED on hello.c before the fix: decode still held the pair (0xe0, 0xe4)
# while fetch replaced its record with (0xf0, 0xf4). The pair (0xe8, 0xec) —
# `li a4,16` and the store that prints it — was destroyed, and the program's
# last print_int(16) never happened.
#
# Decode and dispatch each bind ONE arbiter, where "any" and "all" are the same
# term, which is why fetch was the only stage that lost instructions.

from __future__ import annotations

import inspect
import re

from kathryn import build_model, reset

from carolyne.uarch.o3.decode import Decode
from carolyne.uarch.o3.dispatch import Dispatch
from carolyne.uarch.o3.fetch import Fetch
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config


def test_fetch_requires_every_arbiter_to_grant():
    source = inspect.getsource(Fetch.transfer)
    assert re.search(r'zync\(\s*pip_metas\s*,\s*mode\s*=\s*"all"', source), \
        "fetch binds several arbiters, so its grant must be the AND of them"


def test_a_single_arb_stage_needs_no_mode():
    """One bind makes any and all the same term: only a LIST needs the mode."""
    for stage in (Decode.transfer, Dispatch.transfer):
        source = inspect.getsource(stage)
        assert "mode=" not in source and "mode =" not in source


def test_fetch_binds_decode_and_every_memory_port():
    lanes = 2
    reset()
    machine = build_model(build_machine(gen_o3_rv32im_config(fe_lanes=lanes, commit_lanes=2)))
    fetch   = machine.core.fetch
    assert len(fetch.read_ports) == lanes
    # the binds are decode's arbiter plus one per port — what "all" must cover
    assert fetch.decode_meta is not None
    assert len({id(port.pip_meta) for port in fetch.read_ports}) == lanes
