# ExecUnit — one execution-unit class of the engine (uop_contract.md §1.2):
# a named unit plus the set of operation kinds it natively executes. The
# unit set IS the kind→FU map (no global registry, and a µop template does
# not name its unit) — a custom function unit is just another ExecUnit an ISA
# declares. An Op may sit in several units; which one claims it is a machine
# configuration choice, resolved at elaboration. Non-Op members raise rather
# than being promoted from strings. No standard catalog ships here: every
# ISA/machine declares the ops and units it needs. Latency and port counts
# land when the issue-port design consumes them.

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable

from .op import Op


@dataclass(frozen=True)
class ExecUnit:
    name : str                  # unit class name, e.g. "alu", "mem"
    ops  : FrozenSet[Op]        # operation kinds this unit executes

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ExecUnit needs a non-empty name")
        object.__setattr__(self, "ops", frozenset(self.ops))   # accept any iterable
        if not self.ops:
            raise ValueError(f"ExecUnit '{self.name}': needs at least one op")
        for op in self.ops:
            if not isinstance(op, Op):
                raise TypeError(
                    f"ExecUnit '{self.name}': ops must be Op objects, got {op!r}")

    def has(self, op: Op) -> bool:
        return op in self.ops

    def op(self, name: str) -> Op:
        """Look an op of this unit up by name (encoding tables carry text)."""
        for candidate in self.ops:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"ExecUnit '{self.name}': no op named '{name}' "
            f"(has: {', '.join(sorted(o.name for o in self.ops))})")

    def op_names(self) -> Iterable[str]:
        return sorted(o.name for o in self.ops)
