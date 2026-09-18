# What the SIM varies about a run. Machine and program knobs are not here —
# they are arguments of the system builder (examples/o3/rv32im/system.py).

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimOptions:
    """The simulator-side knobs, with the defaults a plain `run` uses."""

    sim    : str  = "verilator"
    waves  : bool = False
    expect : str  = "host"       # host | none | a path to the expected text
