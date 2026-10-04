# THE DRIVER'S BASE — what HostDriver is written against and what it returns:
# the two abstract classes a port supplies, the status and outcome records, and
# the bank interleave the image loader uses.
#
#   WordPort / ResetLine          what a port must supply (cocotb, PYNQ, a test fake)
#   HostStatus / HostRunOutcome   what comes back
#   BridgeMismatch                the bridge is not the one the map describes
#
# stdlib only: this file runs on the board.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import List, Optional, Sequence, Tuple

from .bridge_map import (STATUS_CONSOLE_OVERFLOW, STATUS_CYCLE_LIMIT_HIT, STATUS_EXIT_SEEN,
                         STATUS_FINISHED, STATUS_HOST_WRITE_REFUSED, STATUS_STARTED)


class BridgeMismatch(RuntimeError):
    """The bridge on the other end is not the one this map describes."""


# ---- what a port must supply -------------------------------------------------------

class WordPort(ABC):
    """One 32-bit word in or out of the window, and a way to wait."""

    @abstractmethod
    async def read(self, addr: int) -> int: ...

    @abstractmethod
    async def write(self, addr: int, word: int) -> None: ...

    @abstractmethod
    async def pause(self, seconds: float) -> None:
        """Let time pass between two polls (clock edges in simulation, sleep on the board)."""


class ResetLine(ABC):
    """The machine's mrst, as the host reaches it."""

    @abstractmethod
    async def hold(self) -> None: ...

    @abstractmethod
    async def release(self) -> None: ...


# ---- what comes back -----------------------------------------------------------------

@dataclass(frozen=True)
class HostStatus:
    """REG_STATUS, bit by bit."""

    word               : int
    started            : bool
    finished           : bool
    exit_seen          : bool
    cycle_limit_hit    : bool
    console_overflow   : bool
    host_write_refused : bool

    @classmethod
    def from_word(cls, word: int) -> "HostStatus":
        return cls(word               = word,
                   started            = bool(word & STATUS_STARTED),
                   finished           = bool(word & STATUS_FINISHED),
                   exit_seen          = bool(word & STATUS_EXIT_SEEN),
                   cycle_limit_hit    = bool(word & STATUS_CYCLE_LIMIT_HIT),
                   console_overflow   = bool(word & STATUS_CONSOLE_OVERFLOW),
                   host_write_refused = bool(word & STATUS_HOST_WRITE_REFUSED))


@dataclass(frozen=True)
class HostRunOutcome:
    """The raw facts of one run, before any rendering."""

    stop_reason        : str                        # exit | max_cycles | timeout
    cycles             : int
    exit_code          : Optional[int]
    console            : List[Tuple[int, int]]      # (tag, word) in program order
    console_overflow   : bool
    host_write_refused : bool
    status_word        : int

    def to_dict(self) -> dict:
        data            = asdict(self)
        data["console"] = [list(entry) for entry in self.console]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "HostRunOutcome":
        data            = dict(data)
        data["console"] = [tuple(entry) for entry in data["console"]]
        return cls(**data)


def interleave_banks(banks: Sequence[Sequence[int]]) -> List[int]:
    """The flat word image of interleaved banks: word w is banks[w % n][w // n].

    - the bridge writes a FLAT image and EasyMem routes each word to its bank,
      so the per-bank files compile_tool writes are folded back together here
    """
    if not banks:
        raise ValueError("interleave_banks: no banks")
    depth = len(banks[0])
    if any(len(bank) != depth for bank in banks):
        raise ValueError("interleave_banks: every bank must hold the same number of words")
    return [banks[w % len(banks)][w // len(banks)] for w in range(depth * len(banks))]
