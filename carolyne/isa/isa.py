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
#
# Decisions (2026-08-15):
# - `atomic_operands`, `operands` and `uops` are declared here too, on exactly
#   the terms `ops` and `reg_files` already are: an ISA writes down its whole
#   vocabulary and the container holds the mops to it. The chain is checked
#   one link at a time — a mop's µops must be declared, their operands must be
#   declared, and those operands' cores must be declared — so a rule that was
#   never written down cannot reach elaboration by riding inside a mop.
# - All three match by IDENTITY, like reg_files and unlike ops. Two reasons:
#   they are unhashable anyway (an Operand reaches a RegFile, which holds a
#   dict), and identity is the discipline the description layer already
#   depends on — a per-ISA package shares operand constants so that every
#   template naming rs1 names ONE object (riscv/operand.py), and a crack that
#   quietly built an equal-but-separate rule is exactly what this catches.
# - Declared-but-unused stays legal for all three, matching the rule for units
#   and reg files: a package may write down a rule before a crack uses it.
# - Duplicates are rejected by instance, since none of the three has a name to
#   key on. Value-equal twins are fine (riscv's AOPR_SRC_1/2 are two slots
#   that agree); the SAME object listed twice is a description bug.
# - Cost, and it is real: an ISA whose operands cannot be shared constants
#   must still list them. x86 µtemp operands are built per crack and never
#   shared (reg.py), so mini-x86 will declare a long `operands` tuple, most
#   likely assembled by the crackers rather than hand-written.
# - LIMIT: the reg-file check still walks what operands SELECT, not what their
#   cores offer. A two-target core carrying a RegFile no operand ever selects
#   is not "used", so it need not be declared — worth revisiting if an ISA
#   ever leaves a candidate unselected on purpose.
#
# Decisions (2026-08-16) — instruction addressing:
# - Three scalars join the vocabularies: `pc_width`, `pc_align`, `ilen_bytes`.
#   They are one subject — how instruction addresses work — and the container
#   had none of them. PC is deliberately not a register class (§4.3, and
#   riscv/reg.py says why), but its WIDTH is still an ISA fact: fetch, the
#   redirect path, the branch-target adder and the ROB's pc field cannot be
#   sized without it. The contract doc has the same gap — §4.3 claims the ISA
#   influences the PC "only via `br` fields and `ilen`", which is not enough to
#   size a single wire. `ilen_bytes` is §6 deliverable three, which until now
#   had no home in the container: riscv/field_match.py held ILEN_BYTES with a
#   comment saying this is where it belongs.
# - DECLARED, not derived, on exactly the terms `ops` and `reg_files` are. The
#   tempting derivation — pc_width from the integer register class — would make
#   the container name a specific class, which is the one thing it must never
#   do, and would make a typo self-consistent. (A per-ISA package may still say
#   `PC_WIDTH = X_LEN`: that is the ISA stating its own spec, not the container
#   inferring one.)
# - REQUIRED, no defaults. A default `pc_width = 32` is a silent wrong answer
#   for a 64-bit ISA, and this layer's whole bargain is that a bad description
#   fails at construction rather than deep in elaboration.
# - Three plain fields, NOT a small `InstrAddr` type holding them. The container
#   states them itself, so nothing new has to be imported to read an ISA's
#   addressing, and the cross-checks below can hold all three to each other in
#   the one __post_init__ that already runs. A type earns its place the day
#   `ilen_bytes` grows its second form — §1.3's pure function over the prefix
#   window, for a variable-length ISA — because that form needs validation of
#   its own. Until x86mini shows what that function looks like, the constant is
#   the whole story and a type would be a wrapper around one int.
# - `pc_align` stores BYTES and derives `pc_align_bits`, the same bargain
#   RegFile makes with `amount`/`index_width`: store the count the description
#   states, derive the log2 the hardware wants, so the two can never disagree.
#   Those are the always-zero low bits of every instruction address — what lets
#   the ROB store a narrowed PC.
# - The cross-checks are what loose scalars could not do alone: `pc_align` a
#   power of two (alignment is a mask, not a modulus), `ilen_bytes` a multiple
#   of it (a sequence of aligned steps from an aligned start stays aligned), and
#   `pc_width` wide enough to address past one aligned unit.
# - NOT here: the reset vector. Where a core starts fetching is a machine
#   configuration choice, not something the ISA states.

# Decision (2026-08-19) — atomic_operands_for(unit):
# - The unit→core direction, added because the elaborator building ONE FU has
#   to size that unit's operand ports and the container could only answer the
#   question the other way round (units_for). It is units_for() walked the long
#   way: unit → its ops → the µops some mop cracks to that name one → their
#   slots → the cores those slots are built on.
# - Composed on the spot instead of adding public uops_for()/operands_for()
#   steps: nothing has asked for the intermediate hops yet, and each is one
#   generator line the day something does.
# - TWO public halves, src_ and dest_, not one call returning both: they are
#   different hardware — the source cores size a unit's READ ports, the dest
#   cores its WRITE ports — so a caller almost always wants one of them, and
#   the pair-returning form would make every call site unpack and re-label
#   what the method name can just say. Wanting both is `a + b`.
# - The halves are disjoint by construction: role lives in the CORE, and Uop
#   cross-checks it against slot position (operand.py), so "filter the walk by
#   role" and "walk uop.srcs / uop.dests" are the same partition. The filter is
#   what the shared _cores_for() runs on, which keeps one walk for both.
# - It walks what the MOPS reach (_uops), not the declared `uops` tuple, so it
#   agrees with the used_* family above: a template no mop cracks to cannot
#   reach any unit at run time, so it is not that unit's problem. Empty is a
#   legal answer — a unit may list ops this ISA never uses (2026-08-14).
# - An undeclared unit is NOT rejected, exactly as units_for() does not check
#   that its Op was declared: both are pure queries over the argument, and the
#   caller got the unit from somewhere. Only the TYPE is held, because passing
#   the NAME is the plausible slip and a bare AttributeError would not say that
#   self.unit(name) is the sanctioned text→unit door.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .atomic_operand import AtomicOperand, OperandRole
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
        """Every architectural class a used operand SELECTS.

        Identity, not equality: two RegFiles with the same fields are still
        two classes, and the elaborator builds a PRF per instance.
        """
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
        """Units that can execute this op — the kind→FU map, read out.

        More than one is not an error: which unit issues a µop is the
        elaborator's scheduling choice (see exec_unit.py).
        """
        return tuple(unit for unit in self.exec_units if unit.has(op))

    def src_atomic_operands_for(self, unit: ExecUnit) -> Tuple[AtomicOperand, ...]:
        """The cores this exec unit READS — one per distinct source slot of
        the µops it executes, so their count is what sizes its read ports."""
        return self._cores_for(unit, OperandRole.SRC)

    def dest_atomic_operands_for(self, unit: ExecUnit) -> Tuple[AtomicOperand, ...]:
        """The cores this exec unit WRITES — the write-port side of the same
        walk, disjoint from the src half because role lives in the core."""
        return self._cores_for(unit, OperandRole.DEST)

    def _cores_for(self, unit: ExecUnit, role: OperandRole) -> Tuple[AtomicOperand, ...]:
        """The walk behind both halves — units_for() read the long way round,
        one hop per line below.

        Deduped by identity like the other used_* walkers. Only the op hop
        matches by VALUE (op.py); everything under it is one shared instance,
        which is why a package shares its operand constants. Empty is a legal
        answer: a unit may run nothing the mops crack to. Full reasoning in
        the header, 2026-08-19.
        """
        if not isinstance(unit, ExecUnit):
            raise TypeError(
                f"IsaBase '{self.name}': an exec-unit query wants an ExecUnit, got "
                f"{type(unit).__name__} (self.unit(name) is the text→unit door)")

        runs  = (uop for uop in self._uops() if unit.has(uop.op))       # µops it executes
        slots = (opr for uop in runs for opr in uop.srcs + uop.dests)   # their operand slots
        return _by_identity(opr.atomic for opr in slots                 # the cores under
                            if opr.role is role)                        # the asked-for half
