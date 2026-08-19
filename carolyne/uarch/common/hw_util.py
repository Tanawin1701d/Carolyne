# Elaboration-time arithmetic every block reaches for. Pure Python on ints — no
# Kathryn import, nothing here builds hardware, and nothing names an ISA.
#
# `ceil_log2` names the repo's most-repeated idiom, `(n - 1).bit_length()`.
# It returns 0 for n == 1 — correct as a log, and NOT a legal Kathryn width, so
# a caller sizing a signal with it must decide what one entry means.
#
# `rotate_left` lives in Kathryn (`combinational.py`, exported from the package
# root), not here: it builds hardware, and inside Kathryn it can read its width
# off the signal. Import it from `kathryn`.

from __future__ import annotations


def ceil_log2(amount: int) -> int:
    """Bits needed to index `amount` things: ceil(log2(amount)).

    0 for a single item — a log, not a width.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError(f"ceil_log2 takes an int, got {type(amount).__name__}")
    if amount < 1:
        raise ValueError(f"ceil_log2 needs a positive count, got {amount}")
    return (amount - 1).bit_length()
