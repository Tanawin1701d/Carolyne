# Bit-pattern questions asked at construction time. Pure Python on ints — no
# Kathryn, nothing here builds hardware, and nothing names an ISA, which is
# what lets BOTH planes reach it (`isa/` may not import `uarch/`).
#
# These are PREDICATES, not raisers: every caller refuses for its own hardware
# reason (a pointer that wraps mod its table, an alignment used as a mask) and
# that reason belongs in that caller's message. What repeats is the bit trick,
# and only the bit trick lives here.

from __future__ import annotations


def is_power_of_two(value: int) -> bool:
    """`value` is 2**k for some k >= 0.

    ZERO IS NOT: the bare `v & (v - 1)` idiom answers 0 for it, so a caller
    writing the trick inline accepts an empty table by accident.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"is_power_of_two takes an int, got {type(value).__name__}")
    return value > 0 and not (value & (value - 1))
