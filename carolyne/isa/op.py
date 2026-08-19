# Op — one operation kind (uop_contract.md §1.2/§2): the `kind` a µop
# template names and the hardware-plane record carries, as a first-class
# object instead of a bare string.
#
# Standalone, not owned by a unit: the same Op may sit in several ExecUnits.
# Value equality on the name, so Op("ADD") == Op("ADD") and two description
# files naming one op name the same op. Not an enum — an op a custom FU
# declares is as first-class as ADD. v0.1 carries the name only.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    name : str                  # operation kind, e.g. "ADD", "LOAD"

    def __post_init__(self) -> None:
        if not (isinstance(self.name, str) and self.name):
            raise ValueError(f"Op needs a non-empty name, got {self.name!r}")

    def __str__(self) -> str:
        return self.name
