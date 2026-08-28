# Shared helpers for RV32I's exec_stage bodies — the package's sanctioned
# Kathryn (§2 compromise). Every unit body is a flat (µops, value) table over
# these two, so adding a µop to a unit is one table row.

from __future__ import annotations

from kathryn import zif
from kathryn.signal import to_ref

from ..uop import Uop
from .reg import X_LEN

SIGN = 1 << (X_LEN - 1)                 # the sign bit, for signed-order tricks


def uop_hit(src, uops):
    """The record holds any of these µops: one OR-ed guard over the group,
    compared against the `uop_idx` field the record already has. A group is
    one operation encoded twice (add/addi), so it shares one guard."""
    hit = None
    for uop in ((uops,) if isinstance(uops, Uop) else uops):
        term = to_ref(src.uop_idx) == uop.uop_idx
        hit  = term if hit is None else hit | term
    return hit


def drive_by_uop(result, src, cases) -> None:
    """Drive `result` from a (µops, value) table: one independent zif per
    row. Every value is COMPUTED whatever the µop is — the guard picks, it
    never short-circuits — and the rows are mutually exclusive, so the
    drives need no priority between them."""
    for uops, value in cases:
        with zif(uop_hit(src, uops)):
            result *= value
