# THE CONTRACT — what a machine family hands the FPGA flow. The flow builds a
# bitstream from the MACHINE and runs any number of PROGRAMS on it; the two are
# separate records because one bitstream serves every program.
#
# Everything machine-model related is built BEFORE these records exist: the
# emitted Verilog with its HostBridge (rtl_dir, top_module, host_map), and the
# program's images plus the bridge run spec the driver reads (spec_path).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from examples.fpga.bridge import HostMap


@dataclass(frozen=True)
class FpgaMachine:
    """One emitted machine with its HostBridge, as the flow receives it."""

    label         : str                  # names the machine in paths and reports
    target        : str                  # the compile_tool target its programs are built for
    rtl_dir       : str                  # the emitted top.v, its modules and its manifest
    top_module    : str                  # the top module's name inside top.v
    host_map      : HostMap              # the window the bridge decodes
    host_map_path : str                  # the same, as the JSON beside the rtl
    config_knobs  : Dict[str, int]       # what the family's config builder was called with
    config        : Any = field(default=None, compare=False, repr=False)   # in-process only


@dataclass(frozen=True)
class FpgaProgram:
    """One program laid out for a machine, with its bridge run spec written."""

    name       : str
    run_dir    : str                     # where this run's files go
    spec_path  : str                     # the bridge_run_spec.json the driver reads
    c_sources  : Tuple[str, ...]         # for the host oracle
    instr_hex  : Tuple[str, ...]         # one per instruction bank
    data_hex   : str


@dataclass(frozen=True)
class FpgaSystem:
    """A program on a machine: what one run of the flow takes."""

    machine : FpgaMachine
    program : FpgaProgram
