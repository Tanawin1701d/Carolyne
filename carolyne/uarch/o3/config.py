# CPUO3_Config — everything one O3 core is built from: the ISA description, and
# the numbers the description does NOT decide.
#
# The ISA comes in whole, as an IsaBase, and is never copied out of: the config
# DERIVES its hardware numbers instead, so a block reads one object and never
# has to know which half a number came from. The knobs are only what the ISA
# cannot say — how wide the machine is, how deep its structures are, and which
# execution units it builds.
#
# `phy_specs` is a TUPLE OF PAIRS rather than a dict, because a RegFile carries
# `const_regs` and is unhashable; matching by identity is the discipline
# IsaBase already runs on. EVERY renamed class must be listed — there is no
# default size — and a size must EXCEED the class's architectural count, or
# rename can never allocate.
#
# `rsv_specs` is the execution side: one entry per reservation station, naming
# the units it feeds. Between them they must cover every op the ISA's
# instructions use.
#
# `sptag_len` is stated in BITS, the one knob holding a width where every other
# holds a count and derives its log2: a tag is a value records carry and
# compare, not an index into a structure. Blocks use it as written —
# `FetchDT(..., spectag=kaf(cfg.sptag_len))`.
#
# Frozen data, checked at construction: a config that cannot work fails here,
# not deep in elaboration.

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ...isa import ExecUnit, IsaBase, RegFile

# The map from a register class to its physical file size. A dict is impossible
# (RegFile is unhashable — header), so the pairs ARE the map; read one with
# CPUO3_Config.phy_size().
PhySpecs = Tuple[Tuple[RegFile, int], ...]


@dataclass(frozen=True)
class RsvSpec:
    issue_o3  : bool                    # out-of-order issue, or in-order from this station
    size      : int                     # entries
    exec_unit : Tuple[ExecUnit, ...]    # the units this station feeds

    def __post_init__(self) -> None:
        if not isinstance(self.issue_o3, bool):
            raise TypeError(
                f"RsvSpec: issue_o3 must be a bool, got {type(self.issue_o3).__name__}")
        if isinstance(self.size, bool) or not isinstance(self.size, int):
            raise TypeError(
                f"RsvSpec: size must be an int, got {type(self.size).__name__}")
        if self.size < 1:
            raise ValueError(f"RsvSpec: size must be >= 1, got {self.size}")
        object.__setattr__(self, "exec_unit", tuple(self.exec_unit))
        if not self.exec_unit:
            raise ValueError("RsvSpec: names no exec unit, so nothing can issue from it")
        for unit in self.exec_unit:
            if not isinstance(unit, ExecUnit):
                raise TypeError(
                    f"RsvSpec: exec_unit must hold ExecUnit, got {type(unit).__name__}")

    @property
    def label(self) -> str:
        """The station named by what it feeds — it has no name of its own."""
        return "/".join(unit.name for unit in self.exec_unit)

    @property
    def ops(self) -> frozenset:
        """Every op issuable from this station."""
        return frozenset(op for unit in self.exec_unit for op in unit.ops)


@dataclass(frozen=True)
class CPUO3_Config:
    isa         : IsaBase             # the description the core is generated from
    fe_lanes    : int                 # front-end lane
    phy_specs   : PhySpecs            # register class -> physical file size
    rsv_specs   : Tuple[RsvSpec, ...] # one per reservation station
    rob_depth   : int                 # in-flight instructions
    sptag_len   : int                 # speculative tag width, in BITS

    def __post_init__(self) -> None:
        if not isinstance(self.isa, IsaBase):
            raise TypeError(
                f"CPUO3_Config: isa must be an IsaBase, got {type(self.isa).__name__}")
        for field in ("fe_lanes", "rob_depth", "sptag_len"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"CPUO3_Config: {field} must be an int, got {type(value).__name__}")
            if value < 1:
                raise ValueError(f"CPUO3_Config: {field} must be >= 1, got {value}")
        object.__setattr__(self, "phy_specs", tuple(self.phy_specs))
        object.__setattr__(self, "rsv_specs", tuple(self.rsv_specs))
        self._check_phy_specs()
        self._check_rsv_specs()

    # --- construction checks --------------------------------------------------
    def _check_phy_specs(self) -> None:
        listed = []
        for entry in self.phy_specs:
            if not (isinstance(entry, tuple) and len(entry) == 2):
                raise TypeError(
                    f"CPUO3_Config: phy_specs holds (RegFile, size) pairs, got {entry!r}")
            reg_file, size = entry
            if not isinstance(reg_file, RegFile):
                raise TypeError(
                    f"CPUO3_Config: phy_specs is keyed by RegFile, "
                    f"got {type(reg_file).__name__}")
            if isinstance(size, bool) or not isinstance(size, int):
                raise TypeError(
                    f"CPUO3_Config: phy_specs size for class '{reg_file.name}' must be "
                    f"an int, got {type(size).__name__}")
            if not any(declared is reg_file for declared in self.isa.reg_files):
                raise ValueError(
                    f"CPUO3_Config: phy_specs sizes class '{reg_file.name}', which ISA "
                    f"'{self.isa.name}' does not declare (matched by identity — name "
                    f"the same instance the ISA does)")
            if not reg_file.renamed:
                raise ValueError(
                    f"CPUO3_Config: class '{reg_file.name}' is not renamed, so it has "
                    f"no physical file to size")
            if any(seen is reg_file for seen in listed):
                raise ValueError(
                    f"CPUO3_Config: phy_specs sizes class '{reg_file.name}' twice")
            if size <= reg_file.amount:
                raise ValueError(
                    f"CPUO3_Config: {size} physical registers leaves no spare for class "
                    f"'{reg_file.name}' ({reg_file.amount} architectural) — rename could "
                    f"never allocate")
            listed.append(reg_file)

        missing = [rf.name for rf in self.isa.reg_files
                   if rf.renamed and not any(seen is rf for seen in listed)]
        if missing:
            raise ValueError(
                f"CPUO3_Config: no physical file size for renamed class(es) "
                f"{', '.join(missing)} — every renamed class needs one, there is no "
                f"default")

    def _check_rsv_specs(self) -> None:
        if not self.rsv_specs:
            raise ValueError("CPUO3_Config: rsv_specs is empty, so nothing can execute")
        for spec in self.rsv_specs:
            if not isinstance(spec, RsvSpec):
                raise TypeError(
                    f"CPUO3_Config: rsv_specs must hold RsvSpec, "
                    f"got {type(spec).__name__}")
            for unit in spec.exec_unit:
                if not any(declared.name == unit.name for declared in self.isa.exec_units):
                    raise ValueError(
                        f"CPUO3_Config: reservation station '{spec.label}' names exec "
                        f"unit '{unit.name}', which ISA '{self.isa.name}' does not "
                        f"declare")

        # The machine-level counterpart of IsaBase's unrunnable-op check: a unit
        # the ISA declares but no station feeds cannot execute anything.
        issuable = frozenset(op for spec in self.rsv_specs for op in spec.ops)
        stranded = sorted(op.name for op in self.isa.used_ops() if op not in issuable)
        if stranded:
            raise ValueError(
                f"CPUO3_Config: no reservation station can issue op(s) "
                f"{', '.join(stranded)} — the ISA's instructions use them")

    # --- derived from the ISA -------------------------------------------------
    @property
    def pc_width(self) -> int:
        return self.isa.pc_width

    @property
    def instr_width(self) -> int:
        return self.isa.ilen_bytes * 8

    # --- derived from the knobs -----------------------------------------------
    @property
    def rob_idx_width(self) -> int:
        return (self.rob_depth - 1).bit_length()

    def phy_size(self, reg_file: RegFile) -> int:
        """Physical registers for one class — phy_specs read as the map it is."""
        for listed, size in self.phy_specs:
            if listed is reg_file:
                return size
        raise ValueError(
            f"CPUO3_Config: no physical file size for class '{reg_file.name}' "
            f"(sized: {', '.join(rf.name for rf, _ in self.phy_specs) or 'none'})")

    def phy_idx_width(self, reg_file: RegFile) -> int:
        """Bits addressing that class's physical file. Per class, because each
        renamed class gets its own PRF (uop_contract.md Q1)."""
        return (self.phy_size(reg_file) - 1).bit_length()
