# THE BRIDGE RUN SPEC — one program run, as the host-side driver reads it: the
# map it addresses, the images it loads, and when to give up. One JSON file
# in the run directory; the paths in it are RELATIVE to that file, because the
# whole directory is copied to the board and read there.
#
# Two readers: the cocotb board-in-simulation test and run_on_board.py.
#
# stdlib only: this file runs on the board.

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

SPEC_FILE   = "bridge_run_spec.json"
SPEC_ENV    = "CAROLYNE_BRIDGE_RUN_SPEC"     # where the cocotb test finds it
OUT_DIR_ENV = "CAROLYNE_BRIDGE_OUT_DIR"      # where it writes the result (default: the spec's dir)


@dataclass(frozen=True)
class BridgeRunSpec:
    """One run of one program through the HostBridge."""

    name        : str
    host_map    : Dict[str, Any]      # HostMap.to_dict(); the driver rebuilds it
    instr_hex   : List[str]           # one path per instruction bank, in bank order
    data_hex    : str
    cycle_limit : int                 # REG_CYCLE_LIMIT; 0 = run until the exit door
    timeout_s   : float               # how long the host waits before giving up


def write_bridge_run_spec(path: str, spec: BridgeRunSpec) -> None:
    """Write the spec with its image paths made relative to the spec's own directory."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    data              = asdict(spec)
    data["instr_hex"] = [os.path.relpath(p, directory) for p in spec.instr_hex]
    data["data_hex"]  = os.path.relpath(spec.data_hex, directory)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)


def read_bridge_run_spec(path: Optional[str] = None) -> BridgeRunSpec:
    """The spec at `path`, or the one $CAROLYNE_BRIDGE_RUN_SPEC names, paths made absolute."""
    path = path or os.environ.get(SPEC_ENV)
    if not path:
        raise RuntimeError(f"no bridge run spec: pass a path or set ${SPEC_ENV}")
    directory = os.path.dirname(os.path.abspath(path))
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    data["instr_hex"] = [os.path.join(directory, p) for p in data["instr_hex"]]
    data["data_hex"]  = os.path.join(directory, data["data_hex"])
    return BridgeRunSpec(**data)


def read_hex_words(path: str) -> List[int]:
    """One word per line, the Verilog $readmemh text BankImage.to_hex writes."""
    with open(path, "r", encoding="utf-8") as handle:
        return [int(line, 16) for line in handle if line.strip()]
