# RegArchMng — the register architecture of a whole core: one Arf, Prf and Rt
# per architectural register class, built from the config and then addressed as
# a set.
#
# The three blocks below it are each written for ONE class and know nothing about
# any other. This is the object that reads the ISA's list of classes, decides
# what each one needs, and keeps the numbers they share in step.
#
# NOT a Kathryn Module: it declares no hardware of its own, has no ports and
# emits no Verilog, so it is a plain object. It BUILDS IN `__init__`, like the
# blocks it owns — which is the one rule a caller has to know: construct it
# inside an open Kathryn module scope, from the @init of the module that should
# own these blocks. Built from nowhere it panics; built from the wrong @init it
# lands in the wrong module.
#
# EVERY class gets an Arf; only a RENAMED class gets a Prf and an Rt, which is
# what the blocks already say (Rt refuses to be built for an unrenamed class,
# CPUO3_Config refuses to size a physical file for one). `RegClassHw.prf`/`.rt`
# are None exactly when `renamed` is False.
#
# THE PHYSICAL FILE SIZE IS READ ONCE and handed to both the Prf and the Rt —
# Prf sizes its storage from it, Rt derives its `prf_idx` width from it, and if
# the two disagreed the rename table would name registers the file does not
# have. That is the main thing this class exists to guarantee.
#
# PORT COUNTS ARE PARAMETERS, not derived from the config: `fe_lanes` says how
# wide the front end fetches, not how many renames or retirements a cycle
# allows. When the config grows those fields they replace these arguments.
#
# Lookup is BY IDENTITY, scanning a tuple, the same bargain CPUO3_Config makes
# with `phy_specs`. The FAN-OUTS are only the calls that take no per-class
# argument (`on_update_meta`, `on_rename`) plus the mispredict, which takes one
# and says so. Commit is deliberately absent: it needs a port index, an
# architectural index and a physical index per class per port, so a commit stage
# reaches `mng.rt(rf)` / `mng.prf(rf)` and drives them itself.
#
# This file names no Kathryn symbol: it builds Kathryn modules by constructing
# them, which is a different thing from declaring hardware.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from carolyne.isa import RegFile
from carolyne.uarch.o3.arf import Arf
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.prf import Prf
from carolyne.uarch.o3.rt import Rt

# The per-class mispredict argument: a RegFile cannot be a dict key (header), so
# the pairs ARE the map, exactly as CPUO3_Config.phy_specs is.
PhyIdxByClass = Sequence[Tuple[RegFile, object]]


@dataclass(frozen=True, eq=False)
class RegClassHw:
    """The hardware of ONE architectural register class.

    `prf` and `rt` are None exactly when the class is not renamed — it lives in
    the Arf and nowhere else.
    """

    reg_file : RegFile
    arf      : Arf
    prf      : Optional[Prf]
    rt       : Optional[Rt]

    @property
    def is_renamed(self) -> bool:
        return self.prf is not None


class RegArchMng:
    """One Arf, Prf and Rt per register class the ISA declares.

    Construct inside the @init of the module that should own the blocks — see
    the header.
    """

    def __init__(self,
                 config       : CPUO3_Config,
                 rename_ports : int,
                 commit_ports : int) -> None:
        self._check(config, rename_ports, commit_ports)
        self.config       = config
        self.rename_ports = rename_ports
        self.commit_ports = commit_ports
        self.classes      = self._build()

    def __repr__(self) -> str:
        built = ", ".join(entry.reg_file.name for entry in self.classes)
        return f"<RegArchMng {self.config.isa.name}: {built}>"

    # --- construction checks ------------------------------------------------------
    @staticmethod
    def _check(config, rename_ports, commit_ports) -> None:
        """What this class itself knows. The per-block rules — a physical file
        must be a power of two, a renamed class must have a size — belong to Prf
        and CPUO3_Config and are left to them, so there is one statement of each
        rule rather than a copy here that can drift."""
        if not isinstance(config, CPUO3_Config):
            raise TypeError(
                f"RegArchMng: config must be a CPUO3_Config, got {type(config).__name__}")
        for field, count in (("rename_ports", rename_ports),
                             ("commit_ports", commit_ports)):
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError(f"RegArchMng: {field} must be >= 1, got {count!r}")
        if not config.isa.reg_files:
            raise ValueError(
                f"RegArchMng: ISA '{config.isa.name}' declares no register class, so "
                f"there is no architectural state to build")

    # --- build ---------------------------------------------------------------------
    def _build(self) -> Tuple[RegClassHw, ...]:
        built = []
        for reg_file in self.config.isa.reg_files:
            arf = Arf(reg_file)
            prf = rt = None
            if reg_file.renamed:
                # ONE read, handed to both, so the file's size and the rename
                # table's index width cannot disagree (header).
                phy_size = self.config.phy_size(reg_file)
                prf = Prf(reg_file, phy_size,
                          rename_ports = self.rename_ports,
                          commit_ports = self.commit_ports)
                rt  = Rt(self.config, reg_file, phy_size,
                         rename_ports = self.rename_ports,
                         # Rt spells this one singular; same number.
                         commit_port  = self.commit_ports)
            built.append(RegClassHw(reg_file, arf, prf, rt))
        return tuple(built)

    # --- the set ---------------------------------------------------------------------
    @property
    def renamed_classes(self) -> Tuple[RegClassHw, ...]:
        return tuple(entry for entry in self.classes if entry.is_renamed)

    def of(self, reg_file: RegFile) -> RegClassHw:
        """One class's blocks, matched by IDENTITY — name the same instance the
        ISA declares (header)."""
        for entry in self.classes:
            if entry.reg_file is reg_file:
                return entry
        declared = ", ".join(entry.reg_file.name for entry in self.classes)
        raise ValueError(
            f"RegArchMng: no blocks for class '{reg_file.name}' "
            f"(matched by identity; built: {declared})")

    def arf(self, reg_file: RegFile) -> Arf:
        return self.of(reg_file).arf

    def prf(self, reg_file: RegFile) -> Prf:
        entry = self.of(reg_file)
        if entry.prf is None:
            raise ValueError(
                f"RegArchMng: class '{reg_file.name}' is not renamed, so it has no "
                f"physical file — its committed state is the Arf")
        return entry.prf

    def rt(self, reg_file: RegFile) -> Rt:
        entry = self.of(reg_file)
        if entry.rt is None:
            raise ValueError(
                f"RegArchMng: class '{reg_file.name}' is not renamed, so it has no "
                f"rename table — it is read straight out of the Arf")
        return entry.rt