# ExecContext — the interface an ExecUnitBase stage body (`build_exec`, or
# each entry of `stages()`) is written against. It lives in the ISA layer
# because that is who WRITES the bodies; the generator only supplies the
# implementation: the real one (uarch/o3/fu.py) hands out Kathryn signals, a
# test hands out plain Python ints, and one body must build the same result
# under both readings. Declaring it here keeps the direction the layout
# already has — uarch reads the description types, never the reverse — and
# this module imports nothing at all, so it adds no edge inside isa either.
#
# The rules of the bargain:
#
# - VALUES ARE OPAQUE. A body combines them with Python operators only
#   (`+ - & | ^ << >> <` ...) and never imports anything to do it. It may
#   therefore use only operations that mean the same thing on unbounded ints
#   and on fixed-width hardware; sign handling is written structurally
#   (flip the sign bit for a signed compare, XOR-subtract to sign-fill a
#   shift), never through a signed type.
# - A WRITE TRUNCATES to the destination slot's width. That is what a write
#   port does, and it is what lets a body write `a - b` and let wraparound
#   fall out the same way in both worlds.
# - THE BODY ALWAYS EXECUTES. It is building hardware, so every expression is
#   evaluated whatever the runtime values are; `when` guards the EFFECTS
#   (write/keep) inside it, not the Python code. A body must never branch in
#   Python on a runtime value.
#
# Slot names are the unit's declared operand names (`ExecUnitBase.src_operands`
# / `dest_operands` — an AtomicOperand's `name`), the same stems every record
# builds its fields from (uarch/o3/operand_field.py).
#
# NOTE the one asymmetry with the rest of this layer: every other module here
# is frozen DATA, and this is an interface. It is still elaboration-plane —
# it holds no runtime value, only the rules for reaching one.

from __future__ import annotations

from typing import Any, ContextManager, Protocol, runtime_checkable


@runtime_checkable
class ExecContext(Protocol):
    # --- the µop record, read ------------------------------------------------
    def uop_is(self, uop: Any) -> Any:
        """A condition: the record holds this µop. One unit serves every µop it
        declares, so a body branches through `when(uop_is(...))`; the key is
        the description's own template constant, which the record names as its
        `uop_idx`."""
        ...

    def src(self, name: str) -> Any:
        """The value in that source slot — an IMMEDIATE included: an immediate
        operand fills a source slot like any other (RV32I's ImmTarget), so
        there is no separate accessor for one. A slot the µop did not fill
        reads like an idle wire — some value; the µop's guard keeps it out of
        the result."""
        ...

    def pc(self) -> Any:
        """This µop's own PC, read off the record — the one PC-relative input
        (auipc, a jump's link value) an operand cannot name, because PC is not
        a register class."""
        ...

    # --- the µop record, written ---------------------------------------------
    def write(self, name: str, value: Any) -> None:
        """Drive that destination slot, truncated to its width. Subject to the
        enclosing guards; the engine owns what happens next (writeback, ROB,
        bypass)."""
        ...

    # --- stage-to-stage state ------------------------------------------------
    def keep(self, name: str, value: Any) -> None:
        """Carry a value into the following stages of this unit's pipeline —
        a stage register the generator sizes and threads."""
        ...

    def kept(self, name: str) -> Any:
        """Read back a value a previous stage kept."""
        ...

    # --- flow ----------------------------------------------------------------
    def when(self, cond: Any) -> ContextManager[None]:
        """Guard the effects in the block on `cond` (zif). Nesting ANDs."""
        ...

    def until(self, cond: Any) -> None:
        """Hold this stage until `cond` (scwait); back-pressure runs up to the
        station through the stage's arbiter."""
        ...

    def while_(self, cond: Any) -> ContextManager[None]:
        """Repeat the block while `cond` holds (cwhile) — a multi-cycle op."""
        ...
