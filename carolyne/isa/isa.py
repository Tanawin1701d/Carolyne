# IsaBase — the whole description of one ISA, and the single object a
# generator is handed (uop_contract.md §6). It owns the vocabularies that
# everything else in this layer refers to: the architectural register classes,
# the operand cores and the slot rules built on them, the µop templates, the
# ops the ISA speaks, the execution units the machine provides for them, and
# the mops binding encodings to µop sequences — plus the three addressing
# scalars (pc_width, pc_align, ilen_bytes) saying where an instruction sits
# and how long it is. The PC is not a register class (§4.3), but its width is
# still an ISA fact: fetch, the redirect path and the ROB cannot be sized
# without it.
#
# Every vocabulary is DECLARED, never derived from the mops, and the container
# holds the mops to it one link at a time: a mop's µops must be declared, their
# operands must be declared, and those operands' cores must be declared. Ops
# match by VALUE (op.py); reg files, cores, operands and µops match by IDENTITY
# — they are unhashable anyway, and a package shares its constants so that one
# rule is one object. Declared-but-unused is legal throughout: a unit may list
# ops this ISA never uses, and a rule may be written before a crack uses it.
# LIMIT: the reg-file check walks what operands SELECT, not what their cores
# offer, so a candidate no operand ever selects need not be declared.
#
# Named *Base* because a per-ISA package may subclass it for description
# fields this container does not model (mini-x86 prefix/ModRM tables). A
# subclass stays frozen=True and stays DATA: overriding op() / units_for() /
# __post_init__ would put ISA-specific behavior on the elaborator's path.
#
# NOT here: the reset vector (machine configuration, not an ISA fact) and the
# trap policy (§6 deliverable, no type yet).
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .atomic_operand import (AtomicOperand, DEST_ROLES, OperandRole,
                             SRC_ROLES)
from .exec_unit import ExecUnit
from .mop import Mop
from .op import Op
from .operand import Operand
from .reg import RegFile
from .uop import Uop

# Every vocabulary the container holds, and its member type: each is normalized
# to a tuple, held to that type, and required non-empty.
_VOCABULARIES = (("reg_files",       RegFile),
                 ("atomic_operands", AtomicOperand),
                 ("operands",        Operand),
                 ("ops",             Op),
                 ("exec_units",      ExecUnit),
                 ("uops",            Uop),
                 ("mops",            Mop))

# How a duplicate is spotted. These three are looked up by name, so a repeated
# NAME is the bug; the next three have no name to key on, so a repeated
# INSTANCE is. (mops are in neither: nothing keys on them yet.)
_NAMED     = ("reg_files", "ops", "exec_units")
_ANONYMOUS = ("atomic_operands", "operands", "uops")


def _by_identity(items) -> Tuple:
    """Dedup preserving order. These types are unhashable — they reach a
    RegFile, which holds a dict — and are compared by instance anyway."""
    found = {}
    for item in items:
        found.setdefault(id(item), item)
    return tuple(found.values())


def _label(target) -> str:
    """A RegFile or Intermediate, named for an error message."""
    return target.name or f"<{target.width}-bit temp>"


@dataclass(frozen=True)
class IsaBase:
    name            : str                       # ISA name, e.g. "rv32i", "x86mini"
    pc_width        : int                       # bits of program counter (§4.3); the PC is
                                                # engine state, not a register class
    pc_align        : int                       # bytes: every instruction address is a
                                                # multiple of this (RV32I 4, x86 1)
    ilen_bytes      : int                       # instruction length in bytes (§1.3, §6.3).
                                                # A constant means fixed-length: the fetch
                                                # aligner degenerates to the fast path
    reg_files       : Tuple[RegFile, ...]       # architectural register classes
    atomic_operands : Tuple[AtomicOperand, ...] # the value/direction cores
    operands        : Tuple[Operand, ...]       # cores + encoding side: the slot rules
    ops             : Tuple[Op, ...]            # the op vocabulary this ISA speaks
    exec_units      : Tuple[ExecUnit, ...]      # units the machine provides for them
    uops            : Tuple[Uop, ...]           # the µop templates instructions crack to
    mops            : Tuple[Mop, ...]           # encoding → µop-sequence bindings

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("IsaBase needs a non-empty name")
        self._check_addressing()
        self._normalize()
        self._reject_duplicates()
        self._reject_undeclared()
        self._reject_unrunnable_ops()
        self._reject_uncovered_operands()

    # --- construction checks --------------------------------------------------
    def _check_addressing(self) -> None:
        """Hold the three addressing scalars to each other (header, 2026-08-16)."""
        for field, value in (("pc_width",   self.pc_width),
                             ("pc_align",   self.pc_align),
                             ("ilen_bytes", self.ilen_bytes)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"IsaBase '{self.name}': {field} must be an int, "
                    f"got {type(value).__name__}")
            if value < 1:
                raise ValueError(
                    f"IsaBase '{self.name}': {field} must be >= 1, got {value}")

        if self.pc_align & (self.pc_align - 1):
            raise ValueError(
                f"IsaBase '{self.name}': pc_align must be a power of two "
                f"(alignment is a mask), got {self.pc_align}")
        if self.ilen_bytes % self.pc_align:
            raise ValueError(
                f"IsaBase '{self.name}': ilen_bytes {self.ilen_bytes} is not a multiple "
                f"of pc_align {self.pc_align} — stepping by it would leave an aligned "
                f"instruction address misaligned")
        if (1 << self.pc_width) <= self.pc_align:
            raise ValueError(
                f"IsaBase '{self.name}': pc_width {self.pc_width} cannot address past "
                f"one aligned unit (pc_align {self.pc_align})")

    def _normalize(self) -> None:
        """Accept any sequence, store a tuple, hold each member to its type."""
        for field, want in _VOCABULARIES:
            members = tuple(getattr(self, field))
            object.__setattr__(self, field, members)
            if not members:
                raise ValueError(f"IsaBase '{self.name}': {field} is empty")
            for member in members:
                if not isinstance(member, want):
                    raise TypeError(
                        f"IsaBase '{self.name}': {field} must hold "
                        f"{want.__name__}, got {type(member).__name__}")

    def _reject_duplicates(self) -> None:
        for field in _NAMED:
            seen = set()
            for member in getattr(self, field):
                if member.name in seen:
                    raise ValueError(
                        f"IsaBase '{self.name}': duplicate {field} name '{member.name}'")
                seen.add(member.name)
        for field in _ANONYMOUS:
            members = getattr(self, field)
            if len({id(member) for member in members}) != len(members):
                raise ValueError(
                    f"IsaBase '{self.name}': {field} lists the same object twice "
                    f"(value-equal twins are fine; one instance is not two)")
        # A core's name is the stem of every hardware field built for it, so two
        # cores sharing one would collide in a record. Unnamed cores are skipped:
        # the name is optional here and required where hardware needs it.
        seen_names = set()
        for core in self.atomic_operands:
            if core.name and core.name in seen_names:
                raise ValueError(
                    f"IsaBase '{self.name}': two atomic operands named '{core.name}' — "
                    f"a core's name has to be unique, it names that slot's fields")
            seen_names.add(core.name)

    def _reject_undeclared(self) -> None:
        """Everything the mops reach must have been written down: the chain
        mop -> µop -> operand -> core, plus the reg files those select."""
        checks = (("uops",            self.used_uops(),
                   lambda m: f"µop '{m.op.name}'"),
                  ("operands",        self.used_operands(),
                   lambda m: f"{m.role} operand on '{_label(m.target)}'"),
                  ("atomic_operands", self.used_atomic_operands(),
                   lambda m: f"{m.role} operand core"),
                  ("reg_files",       self.used_reg_files(),
                   lambda m: f"register file '{m.name}'"))
        for field, used, describe in checks:
            declared = frozenset(id(member) for member in getattr(self, field))
            for member in used:
                if id(member) not in declared:
                    raise ValueError(
                        f"IsaBase '{self.name}': a mop uses {describe(member)}, which "
                        f"the ISA does not declare in {field} (matched by identity — "
                        f"declare the same instance the mops use)")

        # Ops are the exception: they match by VALUE (op.py), so two files
        # naming ADD name the same op and a fresh instance is no error.
        declared_ops = frozenset(self.ops)
        for op in self.used_ops():
            if op not in declared_ops:
                raise ValueError(
                    f"IsaBase '{self.name}': a mop uses op '{op.name}', "
                    f"which the ISA does not declare in ops")

    def _reject_unrunnable_ops(self) -> None:
        for op in self.ops:
            if not any(unit.has(op) for unit in self.exec_units):
                raise ValueError(
                    f"IsaBase '{self.name}': no exec unit executes op '{op.name}' "
                    f"(units: {', '.join(u.name for u in self.exec_units)})")

    # --- derived facts --------------------------------------------------------
    @property
    def pc_align_bits(self) -> int:
        """Low PC bits that are always zero — the ones a stored PC can drop.

        Derived from `pc_align` the way RegFile.index_width is derived from
        `amount`: the description states the count, the hardware wants the
        log2, and deriving is what stops the two from disagreeing. Byte-aligned
        (pc_align == 1) gives 0.
        """
        return self.pc_align.bit_length() - 1

    # --- what the mops actually reach -----------------------------------------
    def _uops(self):
        return (uop for mop in self.mops for seq in mop.uop_seq for uop in seq.uops)

    def used_uops(self) -> Tuple[Uop, ...]:
        """Every µop template some mop's sequence names."""
        return _by_identity(self._uops())

    def used_operands(self) -> Tuple[Operand, ...]:
        """Every operand a used µop fills a slot with, srcs then dests."""
        return _by_identity(o for uop in self._uops() for o in uop.srcs + uop.dests)

    def used_atomic_operands(self) -> Tuple[AtomicOperand, ...]:
        """Every core a used operand is built on."""
        return _by_identity(o.atomic for o in self.used_operands())

    def used_reg_files(self) -> Tuple[RegFile, ...]:
        """Every architectural class a used operand SELECTS, by identity:
        the elaborator builds one PRF per instance."""
        return _by_identity(o.target for o in self.used_operands() if o.is_arch)

    def used_ops(self) -> frozenset:
        """Every op named by a µop of some mop. A set, since ops match by value."""
        return frozenset(uop.op for uop in self._uops())

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
        """Units that can execute this op — the kind→FU map, read out. More
        than one is legal: picking one is the elaborator's choice."""
        return tuple(unit for unit in self.exec_units if unit.has(op))

    def src_atomic_operands_for(self, unit: ExecUnit) -> Tuple[AtomicOperand, ...]:
        """The slots this exec unit READS — its declared port shape, which is
        what a read port is sized from.

        DECLARED, not derived from the µops that happen to reach the unit: a
        port shape is a fact about the unit, and deriving it would make it
        depend on which mops exist. `_reject_uncovered_operands` is what holds
        the µops to it.
        """
        self._check_unit(unit, "src_atomic_operands_for")
        return unit.src_operands

    def dest_atomic_operands_for(self, unit: ExecUnit) -> Tuple[AtomicOperand, ...]:
        """The slots this exec unit WRITES — the write-port side of the same
        declaration. Both dest roles come back; read `is_write_required` to
        tell DEST_W_REQ from a plain DEST."""
        self._check_unit(unit, "dest_atomic_operands_for")
        return unit.dest_operands

    def _check_unit(self, unit, where: str) -> None:
        if not isinstance(unit, ExecUnit):
            raise TypeError(
                f"IsaBase '{self.name}': {where} wants an ExecUnit, got "
                f"{type(unit).__name__} (self.unit(name) is the text→unit door)")

    def _reject_uncovered_operands(self) -> None:
        """No µop may ask a unit for a slot the unit has not got.

        Every unit executing the µop's op must cover it: which unit issues a
        µop is the elaborator's routing choice, so a µop has to run on ANY of
        them. This is the check the declared port shape buys — without it, a
        unit's shape and the instructions using it could drift apart silently.
        """
        for uop in self._uops():
            for unit in self.units_for(uop.op):
                for operand in uop.srcs + uop.dests:
                    if unit.covers(operand.atomic):
                        continue
                    named = operand.atomic.name or f"<{operand.role} slot>"
                    raise ValueError(
                        f"IsaBase '{self.name}': µop '{uop.op.name}' fills a "
                        f"{operand.role} slot '{named}' that exec unit "
                        f"'{unit.name}' does not declare — a unit states the slots "
                        f"it has, and an instruction may not ask for another")
