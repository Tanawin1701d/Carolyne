# ExecUnit — one execution-unit class of the engine (uop_contract.md §1.2):
# a named unit plus the set of operation kinds it natively executes. The
# unit set IS the kind→FU map (no global registry, and a µop template does
# not name its unit) — and a custom function unit is *just another ExecUnit
# instance* an ISA declares.
#
# Decisions (2026-08-13):
# - v0.1 carries name + ops only. Latency/port counts belong to the
#   CustomFu / issue-port design and land when something consumes them.
#
# Decisions (2026-08-14):
# - Ops are `Op` objects, not plain strings (see op.py for why an object and
#   why not an enum). ExecUnit does not own them: it holds a frozenset of
#   ops it can execute, and an Op may appear in several units — which unit
#   claims an op is a machine-configuration choice, resolved against the
#   unit set at elaboration, not stamped into the µop template.
# - Non-Op members raise TypeError at construction rather than being promoted
#   from strings: a silently-accepted "ADD" would compare unequal to the
#   Op("ADD") everything else holds, and only surface as a bogus "no unit
#   executes this op" much deeper in elaboration.
# - `op(name)` exists for the one place a name legitimately arrives as text —
#   an encoding table row naming its op — and fails loudly with the unit's
#   op list rather than returning None.
# - NO standard catalog ships here. The §1.2 table stays spec text and each
#   ISA/machine declares the ops and units it needs: shipping ALU/MEM/... as
#   importable constants would make the natives privileged over an op a
#   custom FU declares, which is exactly the distinction this layer refuses
#   to make — and nothing in the engine consumes such a list yet.

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
