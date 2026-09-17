# Memory SIZES in bytes to the INDEX WIDTH a memory of that size needs — the two
# differ by the bank count and the bus width. This is the one place that
# conversion happens, so no caller computes a width by hand.
#
# NOT here: a machine. Which core runs a program is the caller's choice, stated
# as a CPUO3_Config it hands in (target.py, layout_for).

from __future__ import annotations

from carolyne.util import is_power_of_two

DEFAULT_IMEM_BYTES = 8 * 1024
DEFAULT_DMEM_BYTES = 4 * 1024


def idx_width_for(total_bytes: int, banks: int, word_bytes: int) -> int:
    """The index width one bank needs for a memory of this many bytes.

    A memory holds `banks * 2**index_width * word_bytes` bytes, so the width
    is what is left after the bank count and the bus width are taken out.
    """
    for what, value in (("total_bytes", total_bytes), ("banks", banks),
                        ("word_bytes", word_bytes)):
        if not is_power_of_two(value):
            raise ValueError(
                f"idx_width_for: {what} must be a power of two — the address "
                f"is a part-select, not a compare — got {value}")

    words_per_bank, remainder = divmod(total_bytes, banks * word_bytes)
    if remainder or words_per_bank < 1:
        raise ValueError(
            f"idx_width_for: {total_bytes} bytes does not divide into {banks} "
            f"bank(s) of {word_bytes}-byte words")
    return words_per_bank.bit_length() - 1
