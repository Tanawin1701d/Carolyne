# The Vivado build's summary, as the flow reads it: build_bitstream.tcl writes
# `export/build_summary.txt` as `key value` lines, one fact per line, so no
# Vivado report has to be parsed here.

from __future__ import annotations

import pathlib
from typing import Dict, Union

SUMMARY_FILE = "build_summary.txt"

Fact = Union[int, float, bool, str]

_BOOL_KEYS  = ("timing_met",)
_FLOAT_KEYS = ("wns_ns", "whs_ns", "synth_seconds", "impl_seconds")
_INT_KEYS   = ("lut", "lutram", "ff", "bram", "dsp", "uram")


def parse_build_summary(path: pathlib.Path) -> Dict[str, Fact]:
    """The `key value` lines of build_summary.txt, typed by key."""
    facts: Dict[str, Fact] = {}
    for raw in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        facts[key] = _typed(key, value.strip())
    return facts


def _typed(key: str, value: str) -> Fact:
    try:
        if key in _BOOL_KEYS:  return value.lower() in ("1", "true", "yes")
        if key in _FLOAT_KEYS: return float(value)
        if key in _INT_KEYS:   return int(float(value))
    except ValueError:
        return value
    return value


def describe_summary(facts: Dict[str, Fact]) -> str:
    """The facts a person wants to see after a build, one line."""
    timing = facts.get("timing_met")
    parts  = [f"timing {'met' if timing else 'MISSED' if timing is not None else '?'}"]
    if "wns_ns" in facts:
        parts.append(f"WNS {facts['wns_ns']:.3f} ns")
    for key in ("lut", "lutram", "ff", "bram", "dsp"):
        if key in facts:
            parts.append(f"{key} {facts[key]}")
    return ", ".join(parts)
