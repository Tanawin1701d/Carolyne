# CYCLE EVENTS — the few things per cycle worth naming, read gate first so a
# quiet cycle costs almost no handle reads.
#
#   MEM_WRITE  the store port wrote a word                 (its `enable`)
#   MMIO       that write landed on an I/O word            (the doors below)
#   COMMIT     a commit lane retired an instruction        (its `commit_ok`)
#   REDIRECT   fetch's pc moved somewhere it was not going (a squash, or a taken branch)
#
# NOT here: a per-arbiter FLUSH. An arb's flush wire is declared by the module
# that CALLS flush() — the branch complex, for every arb in the core — so it
# does not resolve from the module holding the arb's probe (probe_pip_status.py's
# LIMIT). REDIRECT is the same fact read where it does resolve.
#
# A stop reason comes from the same events: the exit door, a watchdog that sees
# no progress, or the cycle limit.

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, TextIO

from carolyne.debug.sim import MemPortSimProbe, read_value

# ---- kinds ----------------------------------------------------------------------
MEM_WRITE = "mem_write"
MMIO      = "mmio"
COMMIT    = "commit"
REDIRECT  = "redirect"

# ---- stop reasons ---------------------------------------------------------------
STOP_EXIT       = "exit"
STOP_IDLE       = "idle"
STOP_MAX_CYCLES = "max_cycles"


@dataclass(frozen=True)
class CycleEvent:
    """One thing that happened in one cycle."""
    cycle : int
    kind  : str
    facts : Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MmioDoors:
    """The three I/O words, as WORD indices in the data memory."""
    putchar : int
    putint  : int
    exit    : int

    def name_of(self, index: Optional[int]) -> str:
        """Which door a word index names, or "" when it names none."""
        for name in ("putchar", "putint", "exit"):
            if index == getattr(self, name):
                return name
        return ""

    @classmethod
    def from_layout(cls, layout) -> "MmioDoors":
        """The doors of a compile_tool MemoryLayout, converted to word indices."""
        at = layout.mmio_addrs
        return cls(putchar = layout.data_index(at["putchar"]),
                   putint  = layout.data_index(at["putint"]),
                   exit    = layout.data_index(at["exit"]))


# ---- reading one cycle ------------------------------------------------------------

def read_store_event(store : MemPortSimProbe,
                     doors : MmioDoors,
                     cycle : int) -> Optional[CycleEvent]:
    """The store port's write this cycle: an MMIO when it named a door, else a MEM_WRITE.

    - gate first: with no write, only `enable` is read
    """
    access = store.write_access()
    if access is None:
        return None
    door = doors.name_of(access.index)
    if door:
        return CycleEvent(cycle, MMIO, {"door": door, "index": access.index, "data": access.data})
    return CycleEvent(cycle, MEM_WRITE, {"index": access.index, "data": access.data})


def read_commit_events(commit_ok : Sequence[Any],
                       com_row   : Any,
                       cycle     : int) -> List[CycleEvent]:
    """One event per commit lane that retired, with the row it retired.

    - gate first: a lane that did not retire costs one handle read
    """
    events = []
    for lane, gate in enumerate(commit_ok):
        if read_value(gate) == 1:
            events.append(CycleEvent(cycle, COMMIT, {"lane": lane, **com_row.row(lane)}))
    return events


def read_redirect_event(pc_now     : Optional[int],
                        pc_was     : Optional[int],
                        step_bytes : int,
                        lanes      : int,
                        cycle      : int) -> Optional[CycleEvent]:
    """A pc that did not simply advance: a squash, or a branch that was taken.

    - fetch advances by the lanes the memory answered, so anything from 0 to
      `lanes * step_bytes` is ordinary; anything else is a redirect
    """
    if pc_now is None or pc_was is None or pc_now == pc_was:
        return None
    if 0 < pc_now - pc_was <= lanes * step_bytes:
        return None
    return CycleEvent(cycle, REDIRECT, {"from": pc_was, "to": pc_now})


# ---- what the events mean ----------------------------------------------------------

def apply_console(console, events: Iterable[CycleEvent]) -> None:
    """Send this cycle's character and integer doors to the console."""
    for event in events:
        if event.kind != MMIO:
            continue
        if event.facts["door"] == "putchar":
            console.put_char(event.facts["data"] or 0)
        elif event.facts["door"] == "putint":
            console.put_int(event.facts["data"] or 0)


def exit_code_of(events: Iterable[CycleEvent]) -> Optional[int]:
    """The code stored to the exit door this cycle, or None."""
    for event in events:
        if event.kind == MMIO and event.facts["door"] == "exit":
            return event.facts["data"]
    return None


class StopWatch:
    """When to stop: the exit door, no progress for a while, or the cycle limit.

    - `progress_kinds` is what counts as the machine getting somewhere, so a
      run that reads only the store port watches MMIO and one that also reads
      commit watches that too
    """

    def __init__(self,
                 max_cycles     : int,
                 idle_limit     : int,
                 progress_kinds : Sequence[str] = (COMMIT, MMIO, MEM_WRITE)) -> None:
        self.max_cycles     = max_cycles
        self.idle_limit     = idle_limit
        self.progress_kinds = tuple(progress_kinds)
        self.last_progress  = 0
        self.exit_code      : Optional[int] = None

    def note(self, cycle: int, events: Sequence[CycleEvent]) -> Optional[str]:
        """The reason to stop after this cycle, or None to keep going."""
        code = exit_code_of(events)
        if code is not None:
            self.exit_code = code
            return STOP_EXIT
        if any(event.kind in self.progress_kinds for event in events):
            self.last_progress = cycle
        if cycle - self.last_progress >= self.idle_limit:
            return STOP_IDLE
        if cycle >= self.max_cycles:
            return STOP_MAX_CYCLES
        return None


# ---- writing them out ---------------------------------------------------------------

class EventsWriter:
    """One JSON line per cycle that had events (events.jsonl)."""

    def __init__(self, path: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.handle : Optional[TextIO] = open(path, "w", encoding="utf-8")

    def write(self, cycle: int, events: Sequence[CycleEvent]) -> None:
        if not events:
            return
        line = {"cycle" : cycle,
                "events": [{"kind": e.kind, **e.facts} for e in events]}
        self.handle.write(json.dumps(line) + "\n")

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None
