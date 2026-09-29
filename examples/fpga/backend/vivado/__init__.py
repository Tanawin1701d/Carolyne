# The Vivado backend: a block design around the emitted top — PS, reset GPIO,
# AXI BRAM controller onto the HostBridge window — synthesized, implemented and
# written as a bitstream with its .hwh.
#
#   backend.py     VivadoBackend: fills the templates, runs vivado in batch mode, reads the summary
#   report.py      the build summary the tcl writes, typed
#   boards.json    the boards this backend knows
#   templates/     build_bitstream.tcl (the flow), build_params.tcl.in (its inputs), core_wrapper.v.in

from __future__ import annotations

from .backend import VivadoBackend
from .report  import SUMMARY_FILE, describe_summary, parse_build_summary

__all__ = ["VivadoBackend", "parse_build_summary", "describe_summary", "SUMMARY_FILE"]
