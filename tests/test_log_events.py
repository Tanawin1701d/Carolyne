# Cycle events: what the store port says, what commit says, when a pc is a
# redirect, and when a run should stop.

from __future__ import annotations

import json

import pytest

from carolyne.debug.log.console import ConsoleCapture
from carolyne.debug.log.events import (COMMIT, MEM_WRITE, MMIO, REDIRECT, STOP_EXIT, STOP_IDLE, STOP_MAX_CYCLES,
                                       CycleEvent, EventsWriter, MmioDoors, StopWatch, apply_console, exit_code_of,
                                       read_commit_events, read_redirect_event, read_store_event)
from carolyne.debug.sim import MemPortProbe

DOORS = MmioDoors(putchar=1020, putint=1021, exit=1022)


class _CountingHandle:
    def __init__(self, value: int) -> None:
        self.raw, self.reads = value, 0

    @property
    def value(self) -> int:
        self.reads += 1
        return self.raw


class _Node:
    def __init__(self, **children) -> None: self.__dict__.update(children)


def store_port(enable: int, index: int, data: int):
    node = _Node(index=_CountingHandle(index), data=_CountingHandle(data),
                 enable=_CountingHandle(enable))
    return MemPortProbe(index="i", data="d", enable="e").convert(node), node


# ---- the store port ----------------------------------------------------------------

def test_a_store_to_a_door_is_an_mmio_event():
    port, _node = store_port(1, 1020, ord("h"))
    event = read_store_event(port, DOORS, cycle=7)
    assert event == CycleEvent(7, MMIO, {"door": "putchar", "index": 1020, "data": 104})


def test_a_store_anywhere_else_is_a_plain_memory_write():
    port, _node = store_port(1, 40, 0xdead)
    event = read_store_event(port, DOORS, cycle=7)
    assert event.kind == MEM_WRITE and event.facts == {"index": 40, "data": 0xdead}


def test_no_store_reads_the_gate_and_nothing_else():
    port, node = store_port(0, 1020, 5)
    assert read_store_event(port, DOORS, cycle=7) is None
    assert node.enable.reads == 1 and node.index.reads == 0 and node.data.reads == 0


def test_a_door_is_named_by_its_word_index():
    assert DOORS.name_of(1022) == "exit" and DOORS.name_of(999) == "" and DOORS.name_of(None) == ""


# ---- commit ------------------------------------------------------------------------

class _Table(list):
    pass


class _RowProbe:
    def __init__(self, rows) -> None:
        self.rows_data = rows
        self.reads     = 0

    def row(self, idx):
        self.reads += 1
        return dict(self.rows_data[idx])


def test_only_the_lanes_that_retired_are_read():
    com_row = _RowProbe([{"pc": 0x88}, {"pc": 0x8c}])
    events  = read_commit_events([_CountingHandle(1), _CountingHandle(0)], com_row, cycle=3)
    assert len(events) == 1 and com_row.reads == 1
    assert events[0].kind == COMMIT and events[0].facts == {"lane": 0, "pc": 0x88}


# ---- a redirect --------------------------------------------------------------------

@pytest.mark.parametrize("was, now, is_redirect", [
    (0x88, 0x90, False),      # two lanes of four bytes: an ordinary step
    (0x88, 0x8c, False),      # one lane answered
    (0x88, 0x88, False),      # the stage did not move
    (0x88, 0xa8, True),       # a jump
    (0x88, 0x10, True),       # backwards
    (0x88, 0x94, True),       # further than the front end is wide
])
def test_a_pc_that_did_not_simply_advance_is_a_redirect(was, now, is_redirect):
    event = read_redirect_event(now, was, step_bytes=4, lanes=2, cycle=1)
    assert (event is not None) == is_redirect
    if is_redirect:
        assert event.kind == REDIRECT and event.facts == {"from": was, "to": now}


# ---- what the events mean -----------------------------------------------------------

def test_the_console_takes_the_character_and_integer_doors_only():
    console = ConsoleCapture()
    apply_console(console, [
        CycleEvent(1, MMIO, {"door": "putchar", "index": 1020, "data": ord("h")}),
        CycleEvent(2, MMIO, {"door": "putint",  "index": 1021, "data": 16}),
        CycleEvent(3, MMIO, {"door": "exit",    "index": 1022, "data": 0}),
        CycleEvent(4, MEM_WRITE, {"index": 5, "data": 9}),
    ])
    assert console.text == "h16"


def test_the_exit_door_carries_the_code():
    assert exit_code_of([CycleEvent(1, MMIO, {"door": "exit", "index": 1022, "data": 3})]) == 3
    assert exit_code_of([CycleEvent(1, MEM_WRITE, {"index": 1, "data": 3})]) is None


# ---- when to stop ---------------------------------------------------------------------

def test_the_exit_door_stops_the_run_and_keeps_the_code():
    watch = StopWatch(max_cycles=100, idle_limit=10)
    assert watch.note(1, []) is None
    assert watch.note(2, [CycleEvent(2, MMIO, {"door": "exit", "index": 1022, "data": 0})]) == STOP_EXIT
    assert watch.exit_code == 0


def test_no_progress_for_the_idle_limit_stops_the_run():
    watch = StopWatch(max_cycles=10_000, idle_limit=5)
    for cycle in range(1, 5):
        assert watch.note(cycle, []) is None
    assert watch.note(5, []) == STOP_IDLE


def test_progress_resets_the_watchdog():
    watch = StopWatch(max_cycles=10_000, idle_limit=5)
    for cycle in range(1, 20):
        events = [CycleEvent(cycle, COMMIT, {"lane": 0})] if cycle % 3 == 0 else []
        assert watch.note(cycle, events) is None


def test_only_the_named_kinds_count_as_progress():
    watch = StopWatch(max_cycles=10_000, idle_limit=3, progress_kinds=(MMIO,))
    assert watch.note(1, [CycleEvent(1, COMMIT, {"lane": 0})]) is None
    assert watch.note(3, []) == STOP_IDLE


def test_the_cycle_limit_stops_a_run_that_keeps_moving():
    watch = StopWatch(max_cycles=4, idle_limit=1000)
    busy  = [CycleEvent(0, COMMIT, {"lane": 0})]
    assert watch.note(3, busy) is None
    assert watch.note(4, busy) == STOP_MAX_CYCLES


# ---- the file ---------------------------------------------------------------------------

def test_a_cycle_with_no_events_writes_no_line(tmp_path):
    path   = tmp_path / "events.jsonl"
    writer = EventsWriter(str(path))
    writer.write(1, [])
    writer.write(2, [CycleEvent(2, MMIO, {"door": "putchar", "index": 1020, "data": 104})])
    writer.close()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"cycle": 2, "events": [
        {"kind": "mmio", "door": "putchar", "index": 1020, "data": 104}]}
