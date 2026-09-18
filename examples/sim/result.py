# What one run produced, written where a caller (or a test) can read it back
# without parsing the log.

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class RunResult:
    """One finished run: why it stopped, and what it printed."""

    stop_reason : str                 # exit | idle | max_cycles
    cycles      : int
    exit_code   : Optional[int]
    console     : str
    files       : Dict[str, str] = field(default_factory=dict)

    @property
    def stopped_at_exit(self) -> bool: return self.stop_reason == "exit"


RESULT_FILE = "result.json"


def write_result(path: str, result: RunResult) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(asdict(result), handle, indent=1)


def read_result(path: str) -> RunResult:
    with open(path, "r", encoding="utf-8") as handle:
        return RunResult(**json.load(handle))
