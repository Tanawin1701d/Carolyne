# The host map: the window a host sees through the HostBridge. What is pinned
# is the property the hardware decode leans on — every region starts at a
# multiple of its own size — and the round trips the other readers rely on.

from __future__ import annotations

import pytest

from examples.compile_tool import MachineMem, MemoryLayout
from examples.fpga.bridge import (CONSOLE_TAGS, CONSOLE_WORDS, DMEM, IMEM, MAP_VERSION,
                                  REG_MAGIC, REG_SCRATCH, REGION_ORDER, REGS, HostMap,
                                  interleave_banks, read_hex_words)
from examples.fpga.bridge.bridge_map import is_power_of_two, log2_exact

DOORS = {"putchar": 4092, "putint": 4093, "exit": 4094}


def a_map(imem=8192, banks=2, dmem=16384, depth=4096) -> HostMap:
    return HostMap(imem, banks, dmem, depth, DOORS)


# ---- shape ------------------------------------------------------------------------

def test_the_default_map_lays_out_as_documented():
    m = a_map()
    assert m.regions == {REGS         : (0x00000, 0x1000),
                         CONSOLE_WORDS: (0x04000, 0x4000),
                         CONSOLE_TAGS : (0x08000, 0x4000),
                         IMEM         : (0x0C000, 0x2000),
                         DMEM         : (0x10000, 0x4000)}
    assert m.window_bytes == 0x20000
    assert m.addr_bits    == 17


@pytest.mark.parametrize("imem, banks, dmem, depth", [
    (8192, 2, 4096, 2), (8192, 1, 16384, 4096), (65536, 4, 65536, 16), (4096, 2, 4096, 1024),
])
def test_every_region_is_size_aligned_and_none_overlap(imem, banks, dmem, depth):
    m = a_map(imem, banks, dmem, depth)
    ends = []
    for name in REGION_ORDER:
        base, size = m.regions[name]
        assert is_power_of_two(size) and base % size == 0, name
        assert all(base >= end for end in ends), f"{name} overlaps an earlier region"
        ends.append(base + size)
    assert is_power_of_two(m.window_bytes) and m.window_bytes >= max(ends)
    assert m.addr_bits == log2_exact(m.window_bytes)


def test_region_of_and_entry_addr_agree():
    m = a_map()
    assert m.region_of(0x0000)                     == (REGS, 0)
    assert m.region_of(m.reg_addr(REG_SCRATCH))    == (REGS, REG_SCRATCH)
    assert m.region_of(m.entry_addr(IMEM, 3))      == (IMEM, 12)
    assert m.region_of(m.entry_addr(DMEM, 4095))   == (DMEM, 4095 * 4)
    with pytest.raises(ValueError, match="past region"):
        m.entry_addr(IMEM, 2048)
    for gap in (0x2000, m.window_bytes):            # between regs and the console; past the end
        with pytest.raises(ValueError, match="no region"):
            m.region_of(gap)


# ---- what is refused ------------------------------------------------------------------

@pytest.mark.parametrize("kwargs, message", [
    (dict(imem=6000),   "imem_bytes must be a power of two"),
    (dict(banks=3),     "imem_banks must be a power of two"),
    (dict(depth=1),     "console_depth must be >= 2"),
])
def test_bad_sizes_are_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        a_map(**kwargs)


def test_the_word_width_and_the_doors_are_held():
    with pytest.raises(ValueError, match="4-byte window"):
        HostMap(8192, 2, 4096, 16, DOORS, word_bytes=8)
    with pytest.raises(ValueError, match="doors must name"):
        HostMap(8192, 2, 4096, 16, {"putchar": 1})


# ---- round trips -----------------------------------------------------------------------

def test_json_and_geometry_round_trip(tmp_path):
    m    = a_map()
    path = tmp_path / "host_map.json"
    m.write_json(str(path))
    assert HostMap.read_json(str(path)) == m
    assert HostMap.from_dict(m.to_dict()) == m

    word = m.geometry_word
    assert word & 0xFF         == 13            # log2 8192
    assert (word >> 8)  & 0xFF == 14            # log2 16384
    assert (word >> 16) & 0xF  == 1             # log2 2 banks
    assert (word >> 20) & 0xFF == 12            # log2 4096 entries
    assert (word >> 28) & 0xF  == MAP_VERSION
    assert a_map(depth=1024).geometry_word != word
    assert m.reg_addr(REG_MAGIC) == 0


def test_interleave_banks_matches_the_layouts_instr_slot():
    layout = MemoryLayout.from_spec(MachineMem(imem_base=0, imem_bytes=64, imem_banks=2,
                                               dmem_base=0x10000000, dmem_bytes=4096, word_bytes=4))
    banks  = [[(b << 8) | i for i in range(8)] for b in range(2)]
    flat   = interleave_banks(banks)
    assert len(flat) == 16
    for word_idx, word in enumerate(flat):
        bank, index = layout.instr_slot(word_idx * 4)
        assert word == banks[bank][index]
    with pytest.raises(ValueError, match="same number"):
        interleave_banks([[1, 2], [3]])


def test_read_hex_words_reads_what_to_hex_writes(tmp_path):
    path = tmp_path / "bank.hex"
    path.write_text("00000013\n0000006f\n\n")
    assert read_hex_words(str(path)) == [0x13, 0x6F]
