# IsaDescription — the whole description of one ISA, and the single object a
# generator is handed (uop_contract.md §6). It owns the three vocabularies
# that everything else in this layer refers to: the ops the ISA speaks, the
# execution units the machine provides for them, and the mops (encoding →
# µop-sequence bindings) that make up the instruction set.
#
# Decisions (2026-08-14):
# - `ops` is DECLARED, not derived from the mops or from the units. Deriving
#   it would make a typo self-consistent — a stray Op("ADQ") in one crack
#   would quietly become part of the ISA's vocabulary. Declared instead, the
#   container can cross-check the mops against it (below), which is the check
#   that went missing when Uop dropped its `unit` field: a wrong op has to
#   fail SOMEWHERE, and this is the first place that knows the vocabulary.
# - Two cross-checks at construction, both in the "fail loudly" spirit of the
#   rest of the layer:
#     * every op a mop's µops name must be declared in `ops` (no unknown op
#       reaches elaboration);
#     * every declared op must be executable by at least one exec unit (no
#       op the machine cannot run).
#   The reverse is deliberately allowed: a unit may list ops this ISA never
#   uses, so one ExecUnit definition can be shared across ISAs.
# - Names are unique within each vocabulary (ops, units) because both are
#   looked up by name — an encoding-table row naming its op, a report naming
#   a unit. Duplicate Ops are harmless (value equality) but a duplicate NAME
#   on two different objects is a description bug.
# - No reg files / ilen / trap policy field yet: §6 lists five deliverables
#   and only these three exist as types so far. They join here when built.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .exec_unit import ExecUnit
from .mop import Mop
from .op import Op


@dataclass(frozen=True)
class IsaDescription:
    name       : str                    # ISA name, e.g. "rv32i", "x86mini"
    ops        : Tuple[Op, ...]         # the op vocabulary this ISA speaks
    exec_units : Tuple[ExecUnit, ...]   # units the machine provides for them
    mops       : Tuple[Mop, ...]        # encoding → µop-sequence bindings

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("IsaDescription needs a non-empty name")

        for field, kind, want in (("ops",        "Op",       Op),
                                  ("exec_units", "ExecUnit", ExecUnit),
                                  ("mops",       "Mop",      Mop)):
            members = tuple(getattr(self, field))          # accept any sequence
            object.__setattr__(self, field, members)
            if not members:
                raise ValueError(f"IsaDescription '{self.name}': {field} is empty")
            for member in members:
                if not isinstance(member, want):
                    raise TypeError(
                        f"IsaDescription '{self.name}': {field} must hold {kind}, "
                        f"got {type(member).__name__}")

        self._check_unique_names("ops",        (o.name for o in self.ops))
        self._check_unique_names("exec_units", (u.name for u in self.exec_units))

        declared = frozenset(self.ops)
        for op in self.used_ops():
            if op not in declared:
                raise ValueError(
                    f"IsaDescription '{self.name}': a mop uses op '{op.name}', "
                    f"which the ISA does not declare")
        for op in self.ops:
            if not any(unit.has(op) for unit in self.exec_units):
                raise ValueError(
                    f"IsaDescription '{self.name}': no exec unit executes op "
                    f"'{op.name}' (units: {', '.join(u.name for u in self.exec_units)})")

    def _check_unique_names(self, field: str, names) -> None:
        seen = set()
        for name in names:
            if name in seen:
                raise ValueError(
                    f"IsaDescription '{self.name}': duplicate {field} name '{name}'")
            seen.add(name)

    def used_ops(self) -> frozenset:
        """Every op actually named by a µop of some mop."""
        return frozenset(uop.op
                         for mop in self.mops
                         for seq in mop.uop_seq
                         for uop in seq.uops)

    def op(self, name: str) -> Op:
        """Look an op up by name (encoding tables carry text)."""
        for candidate in self.ops:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"IsaDescription '{self.name}': no op named '{name}' "
            f"(has: {', '.join(sorted(o.name for o in self.ops))})")

    def unit(self, name: str) -> ExecUnit:
        for candidate in self.exec_units:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"IsaDescription '{self.name}': no exec unit named '{name}' "
            f"(has: {', '.join(sorted(u.name for u in self.exec_units))})")

    def units_for(self, op: Op) -> Tuple[ExecUnit, ...]:
        """Units that can execute this op — the kind→FU map, read out.

        More than one is not an error: which unit issues a µop is the
        elaborator's scheduling choice (see exec_unit.py).
        """
        return tuple(unit for unit in self.exec_units if unit.has(op))
