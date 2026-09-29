# What the FLOW varies about a run. Machine and program knobs are not here —
# they are arguments of the machine-side builders (examples/o3/core/fpga_system.py).

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FpgaOptions:
    """The flow-side knobs, with the defaults a plain `run` uses."""

    backend              : str           = "vivado"
    board                : str           = "kv260"
    clock_mhz            : int           = 50
    jobs                 : int           = 8
    synth_only           : bool          = False     # stop after synthesis: reports, no bitstream
    allow_timing_failure : bool          = False     # deploy a bitstream that missed timing
    expect               : str           = "host"    # host | none | a path to the expected text
    board_link           : Optional[str] = None      # the credentials file; None = the default one
