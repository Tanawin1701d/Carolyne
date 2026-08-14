# Op — one operation kind (uop_contract.md §1.2/§2): the `kind` a µop
# template names and the hardware-plane record carries, as a first-class
# object instead of a bare string.
#
# Decisions (2026-08-14):
# - An Op is STANDALONE, not owned by an ExecUnit. Units keep a set of the
#   ops they execute (ExecUnit.ops) and the same Op may sit in more than one
#   unit (a second ALU, a vector unit that also does ADD). A Uop names only
#   its op; routing is ExecUnit.ops read the other way round, resolved
#   against the machine's unit set at elaboration.
# - Value equality on the name: Op("ADD") == Op("ADD"). Two spellings of one
#   catalog entry must BE the same op, otherwise an ISA package that
#   re-declares one silently fails unit membership at Uop construction.
#   Identity semantics belong to Intermediate (every instance is a distinct
#   runtime value); an op kind is a name drawn from a fixed catalog.
# - v0.1 carries the name only. The object exists so per-op facts (latency,
#   pipelining, operand arity, FU semantics hooks) have somewhere to land
#   when a consumer needs them — same deferral rule as ExecUnit's ports.
# - Still not an enum: an op a custom FU declares must be exactly as
#   first-class as ADD, so the standard catalog is just a set of contract-
#   owned Op constants (exec_unit.py), never a closed type.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    name : str                  # operation kind, e.g. "ADD", "LOAD"

    def __post_init__(self) -> None:
        if not (isinstance(self.name, str) and self.name):
            raise ValueError(f"Op needs a non-empty name, got {self.name!r}")

    def __str__(self) -> str:
        return self.name
