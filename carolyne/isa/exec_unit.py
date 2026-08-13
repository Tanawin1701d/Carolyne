# ExecUnit — one execution-unit class of the engine (uop_contract.md §1.2):
# a named unit plus the set of operation kinds it natively executes. A µop
# template names its unit explicitly (Uop.unit), so kind→FU routing is
# visible in the description instead of hiding in a global map — and a
# custom function unit is *just another ExecUnit instance* an ISA declares;
# nothing about the standard catalog is special to the engine.
#
# Decisions (2026-08-13):
# - v0.1 carries name + ops only. Latency/port counts belong to the
#   CustomFu / issue-port design and land when something consumes them.
# - Ops are plain strings (validated against the unit at Uop construction);
#   an enum would make custom-FU kinds second-class citizens.
# - The standard catalog below is CONTRACT-owned (§1.2 table), not per-ISA:
#   ISA packages import these constants and may add custom units, but never
#   redefine the natives.

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class ExecUnit:
    name : str                  # unit class name, e.g. "alu", "mem"
    ops  : FrozenSet[str]       # operation kinds this unit executes

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ExecUnit needs a non-empty name")
        object.__setattr__(self, "ops", frozenset(self.ops))   # accept any iterable
        if not self.ops:
            raise ValueError(f"ExecUnit '{self.name}': needs at least one op")
        for op in self.ops:
            if not (isinstance(op, str) and op):
                raise ValueError(
                    f"ExecUnit '{self.name}': ops must be non-empty strings, got {op!r}")

    def has(self, op: str) -> bool:
        return op in self.ops


# The v0.1 standard catalog — mirrors the table in uop_contract.md §1.2.
ALU     = ExecUnit("alu",     {"ADD", "SUB", "AND", "OR", "XOR",
                               "SLL", "SRL", "SRA", "SLT", "SLTU", "MOV_IMM"})
MULDIV  = ExecUnit("muldiv",  {"MUL", "MULH", "MULHU", "MULHSU",
                               "DIV", "DIVU", "REM", "REMU"})
MEM     = ExecUnit("mem",     {"AGU", "LOAD", "STORE"})
CONTROL = ExecUnit("control", {"BR_COND", "JMP", "JMP_INDIRECT", "CALL_LINK"})
SYSTEM  = ExecUnit("system",  {"SERIALIZE", "FENCE", "TRAP",
                               "READ_SPECIAL", "WRITE_SPECIAL"})

STANDARD_UNITS = (ALU, MULDIV, MEM, CONTROL, SYSTEM)
