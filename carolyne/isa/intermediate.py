# Intermediate value — a µtemp (uop_contract.md §1.4): an intra-instruction
# value produced by one µop of a cracked instruction and consumed by a later
# µop of the SAME instruction. Dead at the instruction boundary by
# construction; renamed like any register class at elaboration.
#
# Identity semantics (eq=False): every instance is a distinct value node. A
# cracker links its µops by reusing the same instance — e.g. x86 `add [m], r`:
#
#     addr = Intermediate(32, "addr")      # AGU  -> addr
#     old  = Intermediate(32, "old")       # LOAD addr -> old
#     new  = Intermediate(32, "new")       # ADD  old, r -> new ; STORE new
#
# The elaborator assigns temp indices; the description layer never numbers them.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, eq=False)
class Intermediate:
    width : int             # bits
    name  : str = ""        # optional debug label, no semantic meaning

    def __post_init__(self) -> None:
        if self.width < 1:
            raise ValueError(f"Intermediate: width must be >= 1, got {self.width}")
