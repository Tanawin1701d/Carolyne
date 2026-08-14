# IsaBase — the whole description of one ISA, and the single object a
# generator is handed (uop_contract.md §6). It owns the vocabularies that
# everything else in this layer refers to: the architectural register
# classes, the ops the ISA speaks, the execution units the machine provides
# for them, and the mops (encoding → µop-sequence bindings) that make up the
# instruction set.
#
# Decisions (2026-08-14):
# - Named *Base* because a per-ISA package may subclass it to carry
#   description fields this container does not model (mini-x86 prefix/ModRM
#   tables). A subclass must stay `@dataclass(frozen=True)` and must stay
#   DATA — overriding op()/units_for()/__post_init__ would put ISA-specific
#   behavior on the path the elaborator walks, which is the one thing the
#   ISA↔µarch split forbids. A plain factory returning IsaBase is the default
#   idiom; subclass only when there are extra fields to carry.
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
# - Names are unique within each vocabulary (reg files, ops, units) because
#   all three are looked up by name — an encoding-table row naming its op, a
#   report naming a unit, rename tables keyed by reg-file name. Duplicate Ops
#   are harmless (value equality) but a duplicate NAME on two different
#   objects is a description bug.
# - `reg_files` gets the same declared-and-cross-checked treatment as `ops`:
#   every RegFile a mop's operands target must be declared here, so the PRF /
#   RAT sizing the elaborator derives cannot miss a class an instruction
#   quietly uses. µtemps (Intermediate) are NOT listed — they are per-crack
#   values with no architectural state, so they have nothing to declare.
#   That check matches by IDENTITY: the elaborator builds one PRF per
#   declared RegFile instance, so a crack targeting an equal-but-different
#   instance really is a second class, and a bug. (RegFile also carries a
#   dict, so it is unhashable and cannot go in a set anyway.)
# - Still no ilen / trap policy field: §6 lists five deliverables and those
#   two have no type yet. They join here when built.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .exec_unit import ExecUnit
from .mop import Mop
from .op import Op
from .reg_file import RegFile


@dataclass(frozen=True)
class IsaBase:
    name       : str                    # ISA name, e.g. "rv32i", "x86mini"
    reg_files  : Tuple[RegFile, ...]    # architectural register classes
    ops        : Tuple[Op, ...]         # the op vocabulary this ISA speaks
    exec_units : Tuple[ExecUnit, ...]   # units the machine provides for them
    mops       : Tuple[Mop, ...]        # encoding → µop-sequence bindings

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("IsaBase needs a non-empty name")

        for field, kind, want in (("reg_files",  "RegFile",  RegFile),
                                  ("ops",        "Op",       Op),
                                  ("exec_units", "ExecUnit", ExecUnit),
                                  ("mops",       "Mop",      Mop)):
            members = tuple(getattr(self, field))          # accept any sequence
            object.__setattr__(self, field, members)
            if not members:
                raise ValueError(f"IsaBase '{self.name}': {field} is empty")
            for member in members:
                if not isinstance(member, want):
                    raise TypeError(
                        f"IsaBase '{self.name}': {field} must hold {kind}, "
                        f"got {type(member).__name__}")

        self._check_unique_names("reg_files",  (r.name for r in self.reg_files))
        self._check_unique_names("ops",        (o.name for o in self.ops))
        self._check_unique_names("exec_units", (u.name for u in self.exec_units))

        declared_ops = frozenset(self.ops)
        for op in self.used_ops():
            if op not in declared_ops:
                raise ValueError(
                    f"IsaBase '{self.name}': a mop uses op '{op.name}', "
                    f"which the ISA does not declare")
        for op in self.ops:
            if not any(unit.has(op) for unit in self.exec_units):
                raise ValueError(
                    f"IsaBase '{self.name}': no exec unit executes op "
                    f"'{op.name}' (units: {', '.join(u.name for u in self.exec_units)})")

        declared_files = frozenset(id(r) for r in self.reg_files)
        for reg_file in self.used_reg_files():
            if id(reg_file) not in declared_files:
                raise ValueError(
                    f"IsaBase '{self.name}': a mop targets register file "
                    f"'{reg_file.name}', which the ISA does not declare "
                    f"(matched by identity — declare the same instance the µops target)")

    def _check_unique_names(self, field: str, names) -> None:
        seen = set()
        for name in names:
            if name in seen:
                raise ValueError(
                    f"IsaBase '{self.name}': duplicate {field} name '{name}'")
            seen.add(name)

    def _uops(self):
        return (uop for mop in self.mops for seq in mop.uop_seq for uop in seq.uops)

    def used_ops(self) -> frozenset:
        """Every op actually named by a µop of some mop."""
        return frozenset(uop.op for uop in self._uops())

    def used_reg_files(self) -> Tuple[RegFile, ...]:
        """Every architectural register file a µop operand targets.

        Identity, not equality: two RegFiles with the same fields are still
        two classes, and the elaborator builds a PRF per instance.
        """
        seen, found = set(), []
        for uop in self._uops():
            for operand in uop.srcs + uop.dests:
                target = operand.target
                if isinstance(target, RegFile) and id(target) not in seen:
                    seen.add(id(target))
                    found.append(target)
        return tuple(found)

    def op(self, name: str) -> Op:
        """Look an op up by name (encoding tables carry text)."""
        for candidate in self.ops:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"IsaBase '{self.name}': no op named '{name}' "
            f"(has: {', '.join(sorted(o.name for o in self.ops))})")

    def unit(self, name: str) -> ExecUnit:
        for candidate in self.exec_units:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"IsaBase '{self.name}': no exec unit named '{name}' "
            f"(has: {', '.join(sorted(u.name for u in self.exec_units))})")

    def reg_file(self, name: str) -> RegFile:
        for candidate in self.reg_files:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"IsaBase '{self.name}': no register file named '{name}' "
            f"(has: {', '.join(sorted(r.name for r in self.reg_files))})")

    def units_for(self, op: Op) -> Tuple[ExecUnit, ...]:
        """Units that can execute this op — the kind→FU map, read out.

        More than one is not an error: which unit issues a µop is the
        elaborator's scheduling choice (see exec_unit.py).
        """
        return tuple(unit for unit in self.exec_units if unit.has(op))
