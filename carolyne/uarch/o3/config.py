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
# the units it feeds and what KIND of station it is. Between them they must
# cover every µop the ISA's instructions use. The kind decides the extra entry
# fields (`RsvType` / `rsv_type_fields`): an exec station carries its pc, a
# branch station its pc and the next one, a load/store station neither — an
# address is a value it computes, not one it is handed. A machine may add more
# through `extra_fields`.
#
# `fe_lanes` and `commit_lanes` are the machine's two widths: how many µops may
# arrive per cycle and how many instructions may retire. Both are CEILINGS the
# hardware is built to — what actually moves in a cycle is whatever is ready —
# so a cycle cannot retire more than the ROB holds, which is checked here.
#
# `sptag_len` is stated in BITS, the one knob holding a width where every other
# holds a count and derives its log2: a tag is a value records carry and
# compare, not an index into a structure. Blocks use it as written —
# `FetchEntryBase(..., spectag=kaf(cfg.sptag_len))`.
#
# Frozen data, checked at construction: a config that cannot work fails here,
# not deep in elaboration.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from ...isa import ExecUnit, IsaBase, RegFile, Uop
from ...util import is_power_of_two
from ..common import ceil_log2

# The map from a register class to its physical file size. A dict is impossible
# (RegFile is unhashable — header), so the pairs ARE the map; read one with
# CPUO3_Config.phy_size().
PhySpecs = Tuple[Tuple[RegFile, int], ...]


# What KIND of station this is, which is what decides the extra fields its
# entries carry. A machine STATES it rather than deriving it from the units:
# two machines may split one unit set differently, and a station feeding
# several kinds of unit still has to say which shape its entries have.
class RsvType(Enum):
    RSV_EXEC   = "exec"      # plain execution
    RSV_BRANCH = "branch"    # resolves control flow
    RSV_LD_ST  = "ld_st"     # memory

    def __str__(self) -> str:
        return self.value


# What each kind adds to an entry, by NAME. Names live here rather than beside
# the widths because a RsvSpec never sees a config and must still check its own
# extras against them; every one of them is PC-shaped today, which is what lets
# rsv_type_fields size them all from pc_width.
_RSV_TYPE_FIELD_NAMES = {
    RsvType.RSV_EXEC  : ("pc",),
    RsvType.RSV_BRANCH: ("pc", "npc"),
    RsvType.RSV_LD_ST : (),
}


def rsv_type_fields(rsv_type: RsvType, pc_width: int) -> Tuple[Tuple[str, int], ...]:
    """The (name, width) pairs one station KIND adds to its entries.

    Sized here rather than on the spec, because a RsvSpec is built standalone
    and never sees the config — the widths are resolved where the machine is.
    """
    if not isinstance(rsv_type, RsvType):
        raise TypeError(
            f"rsv_type must be a RsvType, got {type(rsv_type).__name__} "
            f"({', '.join(t.name for t in RsvType)})")
    return tuple((name, pc_width) for name in _RSV_TYPE_FIELD_NAMES[rsv_type])


@dataclass(frozen=True)
class RsvSpec:
    issue_o3     : bool                    # out-of-order issue, or in-order from this station
    size         : int                     # entries
    exec_unit    : Tuple[ExecUnit, ...]    # the units this station feeds
    rsv_type     : RsvType                 # what kind of station it is
    extra_fields : Tuple[Tuple[str, int], ...] = ()   # (name, width) pairs this
                                                      # machine adds beyond the kind's

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
        if not isinstance(self.rsv_type, RsvType):
            raise TypeError(
                f"RsvSpec '{self.label}': rsv_type must be a RsvType, got "
                f"{type(self.rsv_type).__name__} "
                f"({', '.join(t.name for t in RsvType)})")
        self._check_extra_fields()

    # --- construction checks --------------------------------------------------
    def _check_extra_fields(self) -> None:
        """The machine's own entry fields: well-formed pairs, unique among
        themselves, and not colliding with the ones this kind already adds.

        Only the NAMES can be checked here — a spec never sees the record, so
        a collision with an operand's field is rsv_helper's to catch.
        """
        of_kind = set(_RSV_TYPE_FIELD_NAMES[self.rsv_type])
        seen    = set()
        fields  = []
        for entry in self.extra_fields:
            if not (isinstance(entry, (tuple, list)) and len(entry) == 2):
                raise TypeError(
                    f"RsvSpec '{self.label}': extra_fields holds (name, width) pairs, "
                    f"got {entry!r}")
            name, width = entry
            if not isinstance(name, str) or not name.isidentifier():
                raise ValueError(
                    f"RsvSpec '{self.label}': extra field name {name!r} is not an "
                    f"identifier — it becomes a field name in the entry record")
            if isinstance(width, bool) or not isinstance(width, int):
                raise TypeError(
                    f"RsvSpec '{self.label}': extra field '{name}' width must be an "
                    f"int, got {type(width).__name__}")
            if width < 1:
                raise ValueError(
                    f"RsvSpec '{self.label}': extra field '{name}' is {width} bits — "
                    f"a field with nothing to store is not a legal width")
            if name in of_kind:
                raise ValueError(
                    f"RsvSpec '{self.label}': extra field '{name}' is already added by "
                    f"station kind {self.rsv_type.name}")
            if name in seen:
                raise ValueError(
                    f"RsvSpec '{self.label}': two extra fields named '{name}' — a name "
                    f"is one set of bits")
            seen.add(name)
            fields.append((name, width))
        object.__setattr__(self, "extra_fields", tuple(fields))

    def entry_fields(self, pc_width: int) -> Tuple[Tuple[str, int], ...]:
        """Every ADDED field this station's entries carry: its kind's, then
        whatever this machine put on top."""
        return rsv_type_fields(self.rsv_type, pc_width) + self.extra_fields

    @property
    def label(self) -> str:
        """The station named by what it feeds — it has no name of its own."""
        return "/".join(unit.name for unit in self.exec_unit)

    @property
    def uops(self) -> Tuple[Uop, ...]:
        """Every µop issuable from this station, deduped by identity — the
        discipline the description layer runs on, and a Uop is unhashable
        anyway (it reaches a RegFile, which holds a dict)."""
        found = {}
        for unit in self.exec_unit:
            for uop in unit.uops:
                found.setdefault(id(uop), uop)
        return tuple(found.values())


@dataclass(frozen=True)
class CPUO3_Config:
    isa          : IsaBase            # the description the core is generated from
    fe_lanes     : int                # front-end lanes: how wide fetch/dispatch is
    commit_lanes : int                # AT MOST this many instructions retire in
                                      # one cycle; fewer is the normal case
    phy_specs    : PhySpecs           # register class -> physical file size
    rsv_specs    : Tuple[RsvSpec, ...]# one per reservation station
    rob_depth    : int                # in-flight instructions
    sptag_len    : int                # speculative tag width, in BITS
    st_buf_depth : int                # store-buffer entries (the LSQ's store half)


    def __post_init__(self) -> None:
        if not isinstance(self.isa, IsaBase):
            raise TypeError(
                f"CPUO3_Config: isa must be an IsaBase, got {type(self.isa).__name__}")
        for field in ("fe_lanes", "commit_lanes", "rob_depth", "sptag_len",
                      "st_buf_depth"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"CPUO3_Config: {field} must be an int, got {type(value).__name__}")
            if value < 1:
                raise ValueError(f"CPUO3_Config: {field} must be >= 1, got {value}")
        if self.commit_lanes > self.rob_depth:
            raise ValueError(
                f"CPUO3_Config: {self.commit_lanes} commit lanes over a "
                f"{self.rob_depth}-entry ROB — a cycle cannot retire more "
                f"instructions than the buffer can hold")
        # The pointer-wrap bargain RsvIOR and the ROB already make: circular
        # pointers step modulo the table, so the size is a power of two, and
        # one entry would leave them 0 bits wide.
        if self.st_buf_depth < 2 or not is_power_of_two(self.st_buf_depth):
            raise ValueError(
                f"CPUO3_Config: st_buf_depth must be a power of two >= 2, "
                f"got {self.st_buf_depth}")
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

        # The machine-level counterpart of IsaBase's unrunnable-µop check: a
        # unit the ISA declares but no station feeds cannot execute anything.
        issuable = {id(uop) for spec in self.rsv_specs for uop in spec.uops}
        stranded = sorted(uop.name for uop in self.isa.used_uops()
                          if id(uop) not in issuable)
        if stranded:
            raise ValueError(
                f"CPUO3_Config: no reservation station can issue µop(s) "
                f"{', '.join(stranded)} — the ISA's instructions use them")

    # --- derived from the ISA -------------------------------------------------
    @property
    def pc_width(self) -> int:
        return self.isa.pc_width

    @property
    def instr_width(self) -> int:
        return self.isa.ilen_bytes * 8

    @property
    def uop_idx_width(self) -> int:
        """Bits naming ONE µop of the ISA's vocabulary — the id an in-flight
        record carries to say what it is. Sized from the templates the ISA
        declares, so one index means the same µop anywhere in the core."""
        return ceil_log2(len(self.isa.uops))

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
