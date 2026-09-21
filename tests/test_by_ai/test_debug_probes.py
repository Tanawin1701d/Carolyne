# The debug probes: what a @dbg body stores, what reaches the manifest, that
# debug adds no hardware, and the status rules read back off a sim node.

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest
from kathryn import SignalRef, arena, build_model, emit_verilog, reset
from kathryn.sim.manifest.schema import SIM_MANIFEST_FILE

from carolyne.debug.sim import (BUSY, FLUSH, GRANTED, HELD, IDLE, QUIET, RUNNING, STALL, UNKNOWN, WAITING,
                                KarraySimProbe, PipStatusSimProbe, ProbeBase)
from tests.dbg_toy_model import LOG_ROWS, DbgToy

REPO = pathlib.Path(__file__).resolve().parents[2]


def build_toy() -> DbgToy:
    reset()
    return build_model(DbgToy(), debug=True)      # debug is opt-in: no flag, no @dbg pass


# ---- what a @dbg body stores ---------------------------------------------------

def test_the_probe_base_leaves_convert_to_each_probe():
    with pytest.raises(NotImplementedError, match="ProbeBase.convert"):
        ProbeBase().convert(object())


def test_probe_base_stores_an_optional_signal_only_when_it_exists():
    probe = ProbeBase()
    probe.set_if_bound("absent",  None)
    probe.set_if_bound("present", "a signal")
    assert not hasattr(probe, "absent") and probe.present == "a signal"


def test_a_pip_mastered_arb_carries_the_pip_signals_and_a_sink_does_not():
    m = build_toy()
    for probe in (m.pipe_a, m.pipe_b):
        assert isinstance(probe.pip_wait, SignalRef) and isinstance(probe.pip_ack, SignalRef)
        assert isinstance(probe.mack, SignalRef) and isinstance(probe.mreq, SignalRef)
    assert not hasattr(m.pipe_o, "pip_wait") and not hasattr(m.pipe_o, "pip_ack")
    assert m.pipe_b.hold.global_id == m.hold_b.global_id           # the bound wire itself
    assert not hasattr(m.pipe_a, "hold") and not hasattr(m.pipe_b, "reset")


def test_leaf_lists_follow_creation_order():
    m = build_toy()
    assert len(m.pipe_b.leaf_req) == 2 and m.con_b.pip_leaf.index == 1   # A's zync, then B's pip
    assert len(m.pipe_o.leaf_req) == 1 and m.con_o.pip_leaf is None
    assert len(m.pipe_a.leaf_req) == 1 and m.con_a.pip_leaf.index == 0


def test_the_karray_probe_holds_the_table_and_its_bounds():
    m = build_toy()
    assert m.log_probe.table is m.log and m.log_probe.head is m.wr_ptr and not hasattr(m.log_probe, "count")


def test_without_debug_nothing_is_stored():
    reset()
    m = build_model(DbgToy())
    assert not hasattr(m, "pipe_a") and not hasattr(m, "log_probe")


# ---- the manifest --------------------------------------------------------------

def test_the_manifest_lists_each_probe_as_a_probe_node(tmp_path):
    build_toy()
    emit_verilog(str(tmp_path), "top")
    root = json.loads((tmp_path / SIM_MANIFEST_FILE).read_text())["root"]["children"]
    b    = root["pipe_b"]
    assert b["kind"] == "probe" and "instance" not in b
    kids = b["children"]
    assert kids["pip_wait"]["kind"] == "signal" and kids["pip_wait"]["verilog"].startswith("SR_ST_pip_wait4syn")
    assert kids["mack"]["kind"] == "signal" and kids["hold"]["kind"] == "signal"
    assert kids["leaf_req"]["kind"] == "list" and len(kids["leaf_req"]["items"]) == 2
    assert "pip_wait" not in root["pipe_o"]["children"]
    log = root["log_probe"]["children"]
    assert log["table"]["kind"] == "karray" and log["table"]["shape"] == [LOG_ROWS]
    assert [name for name, _width in log["table"]["fields"]] == ["valid", "data"]
    assert log["head"]["kind"] == "signal"


# ---- debug adds no hardware ----------------------------------------------------

EMIT_SCRIPT = """
import sys
from kathryn import reset, build_model, emit_verilog
from tests.dbg_toy_model import DbgToy, DbgToyBase
reset()
debug = sys.argv[1] == "dbg"
build_model((DbgToy if debug else DbgToyBase)(name="dbg_toy"), debug=debug)   # one name: a subclass would auto-name itself apart
emit_verilog(sys.argv[2], "top")
"""


def emit_in_subprocess(out_dir: pathlib.Path, variant: str) -> bytes:
    # A fresh process each time: global ids are a process-wide counter, so two
    # in-process builds never match byte for byte even when the design does.
    out_dir.mkdir()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), os.environ.get("PYTHONPATH", "")) if p)}
    subprocess.run([sys.executable, "-c", EMIT_SCRIPT, variant, str(out_dir)], check=True, env=env, cwd=REPO)
    return (out_dir / "top.v").read_bytes()


def test_the_verilog_is_byte_identical_with_and_without_debug(tmp_path):
    assert emit_in_subprocess(tmp_path / "dbg", "dbg") == emit_in_subprocess(tmp_path / "base", "base")


# ---- the reader side, on fake sim nodes ----------------------------------------
# `convert` is the MODEL probe's method, so the toy is built once for its instances.

TOY = None


def toy() -> DbgToy:
    global TOY
    if TOY is None:
        TOY = build_toy()
    return TOY


class _Handle:
    # What KSim hands back: any object whose `.value` reads the current bits.
    def __init__(self, value: int) -> None:
        self.value = value


class _Node:
    # A KSim node: attribute per child, and `dir()` lists them (a KSimKarrayElement's fields).
    def __init__(self, **children) -> None:
        self.__dict__.update(children)

    def __dir__(self):
        return sorted(self.__dict__)


class _Table(list):
    # A KSimKarray: len() and [idx] to an element node.
    pass


# con_b really is held by a wire, so its probe stores `hold`: a node that left
# it out would read UNRESOLVED, which is what the UNKNOWN test below pins.
def pip_node(mreq: int, mack: int, pip_wait: int, leaves=(), hold=0, reset=None) -> _Node:
    gates = {name: _Handle(bit) for name, bit in (("hold", hold), ("reset", reset)) if bit is not None}
    return _Node(mreq=_Handle(mreq), mack=_Handle(mack), pip_req=_Handle(0), pip_ack=_Handle(0),
                 pip_wait=_Handle(pip_wait),
                 leaf_req=[_Handle(req) for req, _ack in leaves], leaf_ack=[_Handle(ack) for _req, ack in leaves],
                 **gates)


def sink_node(leaves=()) -> _Node:
    return _Node(mreq=_Handle(int(any(req for req, _ in leaves))), mack=_Handle(1),
                 leaf_req=[_Handle(req) for req, _ack in leaves], leaf_ack=[_Handle(ack) for _req, ack in leaves])


@pytest.mark.parametrize("mreq, mack, pip_wait, word", [
    (1, 1, 0, RUNNING),     # entrance fired with a request: the body is entered
    (1, 1, 1, IDLE),        # parked this cycle: the entry it takes runs after the edge
    (0, 1, 1, IDLE),        # parked, nobody asks
    (0, 1, 0, IDLE),
    (1, 0, 0, HELD),        # asked, entrance did not fire: held or busy
    (0, 0, 0, BUSY),
])
def test_pip_status_truth_table(mreq, mack, pip_wait, word):
    probe = toy().pipe_b.convert(pip_node(mreq, mack, pip_wait))
    assert isinstance(probe, PipStatusSimProbe)
    assert probe.pip_status() == word and probe.parked == pip_wait


def test_pip_status_refuses_an_arb_no_pip_masters():
    with pytest.raises(ValueError, match="no pip"):
        toy().pipe_b.convert(sink_node([(1, 1)])).pip_status()


@pytest.mark.parametrize("req, ack, word", [
    (1, 1, GRANTED),
    (1, 0, WAITING),
    (0, 0, QUIET),
    (0, 1, QUIET),          # an auto_ack leaf: ack is a constant, nothing was asked
])
def test_leaf_status(req, ack, word):
    probe = toy().pipe_b.convert(sink_node([(0, 0), (req, ack)]))
    assert probe.leaf_count == 2 and probe.leaf(1) == (req, ack) and probe.leaf_status(1) == word


@pytest.mark.parametrize("own, gates, next_leaf, word", [
    ((1, 1, 0), {},                      (1, 1), RUNNING),   # the hop is granted
    ((1, 1, 1), {},                      (1, 1), IDLE),      # parked wins over everything
    ((0, 1, 1), {},                      (0, 0), IDLE),
    ((1, 1, 0), {"hold": 1},             (1, 1), STALL),     # its own arbiter is held
    ((1, 1, 0), {"reset": 1},            (1, 1), FLUSH),     # its own arbiter is being reset
    ((1, 1, 0), {"hold": 1, "reset": 1}, (1, 1), STALL),     # hold is read before reset
    ((1, 1, 0), {"hold": 0, "reset": 0}, (1, 0), STALL),     # gates low: the next arbiter did not take it
    ((1, 0, 0), {},                      (0, 0), STALL),
    ((0, 0, 0), {},                      (0, 1), STALL),     # the next leaf's ack without a req is no grant
])
def test_stage_status(own, gates, next_leaf, word):
    own_probe  = toy().pipe_b.convert(pip_node(*own, **gates))
    next_probe = toy().pipe_b.convert(sink_node([next_leaf]))
    assert own_probe.stage_status(next_probe, 0) == word


# ---- a signal out of the holding module's scope --------------------------------
# A leaf's wires are declared by the module that ZYNCS on the arb, and a flush
# wire by the module that calls flush(), so in a multi-module design the probe's
# own module cannot resolve them. The words say UNKNOWN instead of reading 0.

def test_a_stored_signal_the_manifest_cannot_reach_reads_unresolved():
    node = pip_node(1, 1, 0, leaves=[(1, 1)])
    del node.hold                                    # declared by the model, out of scope here
    probe = toy().pipe_b.convert(node)
    assert probe.unresolved == ("hold",) and probe.lost("hold") and not probe.lost("mack")
    assert probe.pip_status() == RUNNING             # reads only what resolved
    assert probe.stage_status(probe, 0) == UNKNOWN   # the gate it needs is gone


def test_an_unresolved_leaf_list_reads_unknown_not_quiet():
    node = pip_node(1, 1, 0, leaves=[(1, 1)])
    del node.leaf_req
    probe = toy().pipe_b.convert(node)
    assert probe.lost("leaf_req") and probe.leaf_count == 0
    assert probe.leaf_status(0) == UNKNOWN and probe.leaf(0) == (None, None)


def test_a_signal_the_model_never_stored_is_not_unresolved():
    # pipe_b's arb has no reset bound, so a node without one is complete.
    probe = toy().pipe_b.convert(pip_node(1, 1, 0, leaves=[(1, 1)]))
    assert "reset" not in probe.unresolved and probe.reset is None


def table_node(rows, **bounds) -> _Node:
    table = _Table(_Node(**{name: _Handle(v) for name, v in row.items()}) for row in rows)
    return _Node(table=table, **{name: _Handle(v) for name, v in bounds.items()})


class _Unknown:
    # A cocotb LogicArray holding X/Z: not resolvable, and int() would raise.
    is_resolvable = False

    def __int__(self):
        raise ValueError("non-0/1 values")


def test_an_unwritten_row_reads_none_not_an_error():
    rows  = [{"valid": 1, "data": 5}, {"valid": 0, "data": 0}]
    node  = table_node(rows)
    node.table[1].data.value = _Unknown()
    probe = toy().log_probe.convert(node)
    assert probe.row(1) == {"valid": 0, "data": None}
    assert probe.live_rows(valid="valid") == [0]


def test_karray_probe_reads_rows_and_live_rows():
    rows  = [{"valid": 1, "data": 5}, {"valid": 0, "data": 0}, {"valid": 1, "data": 7}, {"valid": 0, "data": 0}]
    probe = toy().log_probe.convert(table_node(rows, head=3, count=2))
    assert isinstance(probe, KarraySimProbe) and probe.head is not None
    assert len(probe) == 4 and probe.fields() == ["data", "valid"]
    assert probe.rows() == rows and probe.row(2) == {"valid": 1, "data": 7}
    assert probe.live_rows(valid="valid") == [0, 2]
    assert probe.live_rows() == [3, 0]                                   # the head+count window wraps
    assert toy().log_probe.convert(table_node(rows)).live_rows() == [0, 1, 2, 3]   # no bounds: every row
