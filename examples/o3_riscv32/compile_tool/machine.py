# The machine a program is built for.
#
# The user asks for memory SIZES in bytes; the config wants INDEX WIDTHS, and
# the two differ by the bank count and the bus width. This is the one place
# that conversion happens, so a caller never computes a width by hand and the
# layout is always derived from a config that really was built that way.

from __future__ import annotations

from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.util import is_power_of_two

from ..rv_config import rv32i_config

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


def config_for_sizes(imem_bytes : int = DEFAULT_IMEM_BYTES,
                     dmem_bytes : int = DEFAULT_DMEM_BYTES,
                     **knobs) -> CPUO3_Config:
    """An RV32I machine with memories of the requested size.

    - every other knob passes through to rv_config.rv32i_config
    - the instruction memory has one bank per front-end lane, so its index
      width falls as fe_lanes rises for the same total size
    """
    lanes = knobs.get("fe_lanes", 2)
    probe = rv32i_config(**knobs)               # for ilen_bytes / dlen_bytes
    isa   = probe.isa

    return rv32i_config(
        instr_mem_idx_width = idx_width_for(imem_bytes, lanes, isa.ilen_bytes),
        data_mem_idx_width  = idx_width_for(dmem_bytes, 1, isa.dlen_bytes),
        **knobs)
