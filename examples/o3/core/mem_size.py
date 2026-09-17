# The machine's memory SIZING facts, both directions: bytes to the INDEX
# WIDTH a memory of that size needs (idx_width_for), and a config to the
# whole-machine MachineMem the compile tool takes (machine_mem_of).
#
# NOT here: kathryn. A config builder imports this before any hardware exists.

from __future__ import annotations

from typing import TYPE_CHECKING

from carolyne.util import is_power_of_two

from examples.compile_tool.layout import DMEM_BASE, MachineMem

if TYPE_CHECKING:
    from carolyne.uarch.o3.config import CPUO3_Config


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


def machine_mem_of(config: CPUO3_Config, dmem_base: int = DMEM_BASE) -> MachineMem:
    """compile_tool's view of this machine's memories, DERIVED so the images
    and the hardware cannot disagree.

    - the one place the two vocabularies meet: the config's per-memory specs
      in, the tool's whole-machine MachineMem out
    """
    instr = config.instr_mem_spec()
    data  = config.data_mem_spec()
    return MachineMem(imem_base  = config.reset_pc,
                      imem_bytes = instr.size_bytes,
                      imem_banks = instr.bank_cnt,
                      dmem_base  = dmem_base,
                      dmem_bytes = data.size_bytes,
                      word_bytes = data.data_bus_bytes)
