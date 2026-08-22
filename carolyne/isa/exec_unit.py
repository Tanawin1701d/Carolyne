# ExecUnitBase — one execution-unit class of the engine (uop_contract.md §1.2):
# a named unit, the operation kinds it executes, the operand slots it reads and
# writes, and — for an ISA that supplies them — what it COMPUTES.
#
# The unit set IS the kind→FU map (no global registry, and a µop template does
# not name its unit); a custom function unit is just another unit an ISA
# declares. An Op may sit in several units; which one claims it is a machine
# configuration choice, resolved at elaboration. No standard catalog ships
# here: every ISA/machine declares the ops and units it needs.
#
# THE OPERAND SLOTS ARE DECLARED, not derived from the µops that happen to
# reach the unit. They are the unit's PORT SHAPE — what the elaborator sizes
# read and write ports from — and IsaBase holds every µop to them: an
# instruction may not ask a unit for a slot the unit does not have.
#
# THE SEMANTICS ARE A SUBCLASS'S. `stages()` is the pipeline the unit is — one
# callable per stage, in order — and defaults to a single `build_exec`. A unit
# that overrides neither is still a legal description object; only a generator
# building a real function unit demands one, the same bargain AtomicOperand
# makes with its name. `needs` is what a stage body requires beyond its
# operands, so a generator can build the right context or refuse early.
#
# A stage body is written against the ExecContext (exec_context.py), which is
# why this layer still imports no hardware: the body names slots by their
# operand names and combines opaque values with Python operators, so the same
# body elaborates to Kathryn under the generator and runs on ints under a test.

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Tuple

from .atomic_operand import DEST_ROLES, SRC_ROLES, AtomicOperand
from .exec_context import ExecContext
from .op import Op


@dataclass(frozen=True)
class ExecUnitBase:
    name          : str                        # unit class name, e.g. "alu", "mem"
    ops           : FrozenSet[Op]              # operation kinds this unit executes
    src_operands  : Tuple[AtomicOperand, ...] = ()   # the slots it READS
    dest_operands : Tuple[AtomicOperand, ...] = ()   # the slots it WRITES
    needs         : Tuple[str, ...] = ()       # facilities a stage body asks for,
                                               # e.g. "mem", "redirect", "trap"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ExecUnitBase needs a non-empty name")
        object.__setattr__(self, "ops", frozenset(self.ops))   # accept any iterable
        if not self.ops:
            raise ValueError(f"ExecUnit '{self.name}': needs at least one op")
        for op in self.ops:
            if not isinstance(op, Op):
                raise TypeError(
                    f"ExecUnit '{self.name}': ops must be Op objects, got {op!r}")

        self._check_operands("src_operands",  SRC_ROLES,  "reads")
        self._check_operands("dest_operands", DEST_ROLES, "writes")
        self._check_names()
        object.__setattr__(self, "needs", tuple(self.needs))
        for facility in self.needs:
            if not isinstance(facility, str) or not facility:
                raise ValueError(
                    f"ExecUnit '{self.name}': needs holds facility names, "
                    f"got {facility!r}")

    # --- construction checks --------------------------------------------------
    def _check_operands(self, field: str, roles: tuple, verb: str) -> None:
        """One side of the port shape: the right type, and the right direction."""
        members = tuple(getattr(self, field))
        object.__setattr__(self, field, members)          # accept any sequence
        for member in members:
            if not isinstance(member, AtomicOperand):
                raise TypeError(
                    f"ExecUnit '{self.name}': {field} must hold AtomicOperand, "
                    f"got {type(member).__name__}")
            if member.role not in roles:
                raise ValueError(
                    f"ExecUnit '{self.name}': {field} holds a {member.role} operand — "
                    f"those are the slots the unit {verb}")

    def _check_names(self) -> None:
        """A slot's name becomes a field name in every record built for this
        unit, so two of them cannot share one."""
        seen = set()
        for atm_operand in self.operands():
            if not atm_operand.name:
                continue                                   # named where hardware needs it
            if atm_operand.name in seen:
                raise ValueError(
                    f"ExecUnit '{self.name}': two operand slots named "
                    f"'{atm_operand.name}'")
            seen.add(atm_operand.name)

    # --- the port shape -------------------------------------------------------
    def operands(self) -> Tuple[AtomicOperand, ...]:
        """Every slot this unit has, sources then destinations."""
        return self.src_operands + self.dest_operands

    def covers(self, atm_operand: AtomicOperand) -> bool:
        """This unit has that slot — by IDENTITY, the discipline the whole
        description layer runs on."""
        return any(mine is atm_operand for mine in self.operands())

    # --- ops ------------------------------------------------------------------
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

    # --- what the unit computes -----------------------------------------------
    def stages(self):
        """The pipeline this unit is: one callable per stage, in order.

        One stage by default. A pipelined unit names its own —
        `return (self.partial, self.reduce, self.round)` — and a generator
        builds one pipeline stage per entry.
        """
        return (self.build_exec,)

    def build_exec(self, ctx: ExecContext) -> None:
        """What this unit computes, written against the generator's context.

        `ctx` is the ExecContext (exec_context.py): the record reads and
        writes, plus flow. Values are opaque — Kathryn signals under the real
        generator, plain ints under a test double — so a body combines them
        with Python operators and imports nothing.

        Left to a subclass: the shape of a unit is a description fact, but what
        the bits become is the ISA's to say.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.build_exec: what unit '{self.name}' computes is "
            f"the ISA's to say — override build_exec, or stages() for a pipeline")


# The name a unit with no semantics of its own is built under. Same class: a
# unit that never overrides build_exec is a legal description object, it simply
# cannot be turned into a function unit.
ExecUnit = ExecUnitBase
