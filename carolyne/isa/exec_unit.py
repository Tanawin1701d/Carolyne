# ExecUnitBase — one execution-unit class of the engine (uop_contract.md §1.2):
# a named unit, the µops it executes, the operand slots it reads and writes,
# and — for an ISA that supplies them — what it COMPUTES.
#
# The unit set IS the kind→FU map (no global registry, and a µop template does
# not name its unit); a custom function unit is just another unit an ISA
# declares. One µop may sit in several units; which one claims it is a machine
# configuration choice, resolved at elaboration. No standard catalog ships
# here: every ISA/machine declares the µops and units it needs.
#
# `uops` is a TUPLE matched by IDENTITY, not a frozenset: a Uop reaches a
# RegFile, which holds a dict, so it is unhashable — and identity is the
# discipline the whole description layer runs on, so a unit lists the same
# template constants the ISA declares.
#
# THE OPERAND SLOTS ARE DECLARED, not derived from the µops that happen to
# reach the unit. They are the unit's PORT SHAPE — what the elaborator sizes
# read and write ports from — and IsaBase holds every µop to them: an
# instruction may not ask a unit for a slot the unit does not have.
#
# THE SEMANTICS ARE A SUBCLASS'S. `stage_cnt` declares how many stages the
# unit's pipeline is, and `exec_stage(stage_idx, src, api)` is one stage's
# body: NATURAL KATHRYN (|= *= seq par zif scwait ...) over `src`, the Karray
# record the stage receives, RETURNING the Karray the next stage receives —
# the last stage's return is the writeback record, its dest slots read by
# operand field name. A unit that never overrides exec_stage is still a legal
# description object; only a generator building a real function unit demands
# one, the same bargain AtomicOperand makes with its name.
#
# The generator owns the stage skeleton (the pip/zync chain, the kill) and
# threads rob_des_idx / is_spec / spec_tag between stages ITSELF; everything
# else a later stage needs, the body carries in the record it returns. What a
# body cannot reach with raw Kathryn it reaches through the ExecUnitApi
# (exec_unit_api.py), which the O3 generator overrides. `needs` is what a
# stage body requires beyond its operands, so a generator can build the right
# api or refuse early.
#
# Since 2026-08-28 this is the ISA layer's sanctioned COMPROMISE of the
# no-Kathryn rule: description TYPES still import no hardware (this module's
# hints never evaluate), but a package's semantics — its exec_stage bodies —
# are hardware code and write Kathryn directly.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Tuple

from .atomic_operand import DEST_ROLES, SRC_ROLES, AtomicOperand
from .uop import Uop

if TYPE_CHECKING:                       # hints only — no runtime Kathryn here
    from kathryn import Karray

    from .exec_unit_api import ExecUnitApi


@dataclass(frozen=True)
class ExecUnitBase:
    name          : str                        # unit class name, e.g. "alu", "mem"
    uops          : Tuple[Uop, ...]            # the µop templates this unit executes
    src_operands  : Tuple[AtomicOperand, ...] = ()   # the slots it READS
    dest_operands : Tuple[AtomicOperand, ...] = ()   # the slots it WRITES
    needs         : Tuple[str, ...] = ()       # facilities a stage body asks for,
                                               # e.g. "mem", "redirect", "trap"
    stage_cnt     : int = 1                    # pipeline depth: one exec_stage
                                               # call per stage, in order

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ExecUnitBase needs a non-empty name")
        if isinstance(self.stage_cnt, bool) or not isinstance(self.stage_cnt, int) \
                or self.stage_cnt < 1:
            raise ValueError(
                f"ExecUnit '{self.name}': stage_cnt must be an int >= 1, got "
                f"{self.stage_cnt!r}")
        object.__setattr__(self, "uops", tuple(self.uops))     # accept any sequence
        if not self.uops:
            raise ValueError(f"ExecUnit '{self.name}': needs at least one µop")
        self._check_uops()

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
    def _check_uops(self) -> None:
        """The µops this unit runs: the right type, listed once, named apart.

        By INSTANCE for the duplicate, by NAME for the collision — a name is
        how a body and an encoding table reach a template, so two of them
        cannot share one.
        """
        seen_names = set()
        for pos, uop in enumerate(self.uops):
            if not isinstance(uop, Uop):
                raise TypeError(
                    f"ExecUnit '{self.name}': uops must be Uop objects, got "
                    f"{type(uop).__name__}")
            if any(other is uop for other in self.uops[:pos]):
                raise ValueError(
                    f"ExecUnit '{self.name}': lists µop '{uop.name}' twice")
            if uop.name in seen_names:
                raise ValueError(
                    f"ExecUnit '{self.name}': two µops named '{uop.name}' — a name is "
                    f"how a stage body and an encoding table reach one")
            seen_names.add(uop.name)

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

    # --- µops -----------------------------------------------------------------
    def has(self, uop: Uop) -> bool:
        """This unit runs that µop — by IDENTITY, like every other membership
        question in this layer."""
        return any(mine is uop for mine in self.uops)

    def uop(self, name: str) -> Uop:
        """Look a µop of this unit up by name (encoding tables carry text)."""
        for candidate in self.uops:
            if candidate.name == name:
                return candidate
        raise ValueError(
            f"ExecUnit '{self.name}': no µop named '{name}' "
            f"(has: {', '.join(self.uop_names())})")

    def uop_names(self) -> Iterable[str]:
        return sorted(u.name for u in self.uops)


    # --- the semantics --------------------------------------------------------
    def exec_stage(self, stage_idx: int, src: Karray, api: ExecUnitApi) -> Karray:
        """One stage of what this unit computes, in natural Kathryn.

        - called by the generator INSIDE stage `stage_idx`'s own scope, once
          per stage 0..stage_cnt-1, so the body's scwait/cwhile compose with
          the stage's arbiter and back-pressure runs up to the station
        - `src` is the record this stage receives: stage 0 the station's
          issued entry, stage k the record stage k-1 RETURNED
        - returns a NEW register record for the next stage — never `src`
          itself: the body creates it and writes it inside its
          zync_with_next_stage block. The LAST stage returns None: it has
          no next stage, and its results leave through
          api.wb_reg(atm_opr, value)
        - the generator transfers is_spec/spec_tag from src to des inside
          the sync; everything else the body carries in what it returns
        """
        raise NotImplementedError(
            f"{type(self).__name__}.exec_stage: what unit '{self.name}' computes "
            f"is the ISA's to say — a semantics subclass overrides this")


# The name a unit with no semantics of its own is built under. Same class: a
# unit that never overrides exec_stage is a legal description object, it simply
# cannot be turned into a function unit.
ExecUnit = ExecUnitBase
