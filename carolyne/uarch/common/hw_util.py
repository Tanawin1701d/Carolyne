# Elaboration-time arithmetic every block reaches for. Pure Python on ints — no
# Kathryn import, nothing here builds hardware, and nothing names an ISA.
#
# Decisions (2026-08-17):
# - `ceil_log2` exists to give the repo's most-repeated idiom one name.
#   `(n - 1).bit_length()` already appears as RegFile.index_width,
#   CPUO3_Config.rob_idx_width and Prf.idx_width; written out at a fourth site it
#   stops reading as "the log2 of a count" and starts reading as bit fiddling.
#   It returns 0 for n == 1 — correct as a log, and NOT a legal Kathryn width, so
#   a caller sizing a signal with it must decide what one entry means (RegFile
#   makes exactly this call for a one-register class).
# - `rotate_left` briefly lived here and MOVED to Kathryn (`combinational.py`,
#   exported from the package root). It builds hardware, so it belongs on the
#   other plane; and inside Kathryn it can read its width off the signal, which
#   a caller out here cannot do — SignalRef exposes no public width, only the
#   private `_slice`. Import it from `kathryn`, not from this module.

from __future__ import annotations


def ceil_log2(amount: int) -> int:
    """Bits needed to index `amount` things: ceil(log2(amount)).

    0 for a single item — a log, not a width. See the header.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError(f"ceil_log2 takes an int, got {type(amount).__name__}")
    if amount < 1:
        raise ValueError(f"ceil_log2 needs a positive count, got {amount}")
    return (amount - 1).bit_length()
