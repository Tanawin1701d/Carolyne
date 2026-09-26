# THE RUN SPEC — this package's OWN handoff to its own cocotb test, one JSON
# file beside the emitted Verilog. The sim forwards the environment variable
# naming it and never reads it: the schema is rv32im's to change.
#
# The handoff has to be EXPLICIT: the cocotb test runs in another process and a
# CPUO3_Config is not serialisable, so the spec carries the KNOBS the config
# builder was called with. The test calls this package's own
# gen_o3_rv32im_config with them, so both processes build one machine and
# neither re-derives a width. The images travel as hex FILES for the same
# reason.
#
# Word INDICES, not byte addresses: the I/O doors are what the store port
# reports, and that port names a word.
#
# Both ends are here: build_run_spec fills one from a built program (system.py
# calls it), write/read carry it across, and the cocotb test reads it back.

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from carolyne.debug.log import MmioDoors

# --- the record -----------------------------------------------------------------
SPEC_FILE = "run_spec.json"
SPEC_ENV  = "CAROLYNE_RUN_SPEC"      # where the test finds it


@dataclass(frozen=True)
class RunSpec:
    """One simulation run, as the simulator process reads it."""

    name           : str
    target         : str              # which toolchain built the images; provenance, not a machine
    config_kwargs  : Dict[str, int]   # what gen_o3_rv32im_config was called with, final widths and all
    instr_hex      : List[str]           # one path per instruction bank, in bank order
    data_hex       : str
    doors          : Dict[str, int]      # putchar / putint / exit, as WORD indices
    word_bytes     : int
    pc_step        : int                 # bytes one instruction takes: the pc's ordinary step
    out_dir        : str
    reset_cycles   : int  = 3
    max_cycles     : int  = 20_000
    idle_limit     : int  = 2_000
    log_enabled    : bool = True
    log_window     : int  = 2_500        # rendered cycles the log keeps
    log_chunk      : int  = 0            # rows per file; 0 keeps the window instead
    log_rob_rows   : int  = 4            # reorder-buffer entries the log prints

    def path_in(self, name: str) -> str: return os.path.join(self.out_dir, name)


# --- crossing the process boundary ----------------------------------------------
def write_run_spec(path: str, spec: RunSpec) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(asdict(spec), handle, indent=1)


def read_run_spec(path: Optional[str] = None) -> RunSpec:
    """The spec at `path`, or the one $CAROLYNE_RUN_SPEC names."""
    path = path or os.environ.get(SPEC_ENV)
    if not path:
        raise RuntimeError(f"no run spec: pass a path or set ${SPEC_ENV}")
    with open(path, "r", encoding="utf-8") as handle:
        return RunSpec(**json.load(handle))


def read_hex_words(path: str) -> List[int]:
    """One word per line, the Verilog $readmemh text BankImage.to_hex writes."""
    with open(path, "r", encoding="utf-8") as handle:
        return [int(line, 16) for line in handle if line.strip()]


# --- filling one from a built program -------------------------------------------
def build_run_spec(config,
                   program,
                   run_dir      : str,
                   name         : str,
                   log_enabled  : bool,
                   log_window   : int,
                   log_chunk    : int,
                   log_rob_rows : int,
                   max_cycles   : int,
                   idle_limit   : int,
                   knobs        : dict) -> RunSpec:
    """What the cocotb test needs, taken off the built program.

    - `knobs` are the RECIPE for the machine, not its numbers: the test calls
      gen_o3_rv32im_config with them and re-derives no width of its own
    """
    layout = program.layout
    images = os.path.join(run_dir, "program")
    return RunSpec(
        name           = name,
        target         = "rv32im",
        config_kwargs  = knobs,
        instr_hex      = [os.path.join(images, f"{bank.name}.hex") for bank in program.image.instr_banks],
        data_hex       = os.path.join(images, f"{program.image.data_bank.name}.hex"),
        doors          = vars(MmioDoors.from_layout(layout)),
        word_bytes     = layout.word_bytes,
        pc_step        = config.isa.ilen_bytes,
        out_dir        = run_dir,
        max_cycles     = max_cycles,
        idle_limit     = idle_limit,
        log_enabled    = log_enabled,
        log_window     = log_window,
        log_chunk      = log_chunk,
        log_rob_rows   = log_rob_rows,
    )
