# Fetch and the banked instruction memory — the bank is part of the ADDRESS.
#
# The first test is the whole argument: splitting a byte address into
# | index | bank | zero | IS the interleave rule, so lane L asking for
# pc + L * ilen reaches the word stored at bank w % banks, index w / banks,
# with no rotation logic anywhere. Checked in pure Python, no simulator.
#
# The rest elaborates real hardware (reset -> @init -> gen_flow -> build_flow),
# which is where a bad region width or a zero-width wire actually fails.

from __future__ import annotations

import pytest

from kathryn import *

from carolyne.uarch.mem.common.mem_port import MemPortRead, MemPortReadValid
from carolyne.uarch.mem.easy_mem import EasyMem
from carolyne.uarch.o3.fetch import Fetch
from examples.o3_riscv32.rv_config import rv32i_config

ILEN = 4
ZERO = 2        # log2(ILEN): the byte offset the bus width holds at zero


# --- the address split IS the interleave --------------------------------------
def split(byte_addr: int, bank_bits: int) -> tuple:
    """(index, bank) out of a byte address, the way AddrMeta stacks regions."""
    bank  = (byte_addr >> ZERO) & ((1 << bank_bits) - 1)
    index = byte_addr >> (ZERO + bank_bits)
    return index, bank


@pytest.mark.parametrize("banks", [1, 2, 4, 8])
def test_splitting_the_address_lands_on_the_bank_the_word_is_stored_in(banks):
    """Storage says word w is at bank w % banks, index w / banks. The split
    says the same thing, which is why nothing has to rotate."""
    bank_bits = (banks - 1).bit_length()

    for word in range(64):
        index, bank = split(word * ILEN, bank_bits)
        assert (index, bank) == (word // banks, word % banks), f"word {word}"


@pytest.mark.parametrize("banks", [1, 2, 4])
def test_every_lane_reaches_the_word_the_program_is_actually_at(banks):
    """Lane L asks for pc + L*ilen for ANY aligned pc, and the memory routes
    it. A lane crossing into the next group is a larger address, nothing more."""
    bank_bits = (banks - 1).bit_length()

    for pc in range(0, 64 * ILEN, ILEN):
        for lane in range(banks):
            index, bank = split(pc + lane * ILEN, bank_bits)
            word = index * banks + bank
            assert word * ILEN == pc + lane * ILEN


def test_a_pc_part_way_into_a_group_reaches_the_next_index_by_itself():
    """The case from the design discussion: 4 banks, pc = 0x04. Lane 3 wants
    0x10, which simply HAS index 1 — no wrap rule states it."""
    assert [split(0x04 + 4 * lane, 2) for lane in range(4)] == [
        (0, 1), (0, 2), (0, 3), (1, 0)]


# --- the hardware -------------------------------------------------------------
def _machine(lanes: int):
    """A fetch stage on a real banked memory. Elaborating IS the assertion."""
    config = rv32i_config(fe_lanes=lanes, commit_lanes=lanes)

    class Host(Module):
        @init
        def decl(self):
            self.mem   = EasyMem(*config.instr_mem_spec())
            self.ports = [self.mem.add_read_port(f"lane{k}")
                          for k in range(lanes)]
            self.fetch = Fetch(config, self.ports)
            self.sink  = PipCon()
            self.sink.no_pip_master()
            self.fetch.decode_meta = self.sink

    reset()
    host = Host()
    set_top(host)
    gen_flow()
    build_flow()
    return host


@pytest.mark.parametrize("lanes", [1, 2, 4])
def test_the_stage_elaborates_at_every_lane_count(lanes):
    """One lane must work too: there is no bank region at all there, and a
    zero-width one is what a careless address shape would build."""
    host   = _machine(lanes)
    widths = host.mem.addr_meta.var_widths

    assert len(host.ports) == lanes
    assert widths[0] == host.fetch.config.instr_mem_idx_width
    assert (len(widths) == 1) == (lanes == 1)


def test_the_memory_states_the_bank_as_a_second_address_region():
    config = rv32i_config(fe_lanes=4, commit_lanes=4)

    class Host(Module):
        @init
        def decl(self):
            self.mem = EasyMem(*config.instr_mem_spec())

    reset()
    host = Host()

    assert host.mem.addr_meta.var_widths == (config.instr_mem_idx_width, 2)
    assert host.mem.addr_meta.zero_width == ZERO


@pytest.mark.parametrize("lanes", [1, 4])
def test_the_memory_takes_only_one_write_port(lanes):
    """Each bank has ONE write port and a routed writer reaches every bank, so
    a second writer could name the same bank — and a dropped write is lost
    data, where a dropped read only stalls. True at one bank too."""
    config = rv32i_config(fe_lanes=lanes, commit_lanes=lanes)

    class Host(Module):
        @init
        def decl(self):
            self.mem = EasyMem(*config.instr_mem_spec())
            self.mem.add_write_port("loader")
            with pytest.raises(ValueError, match="ONE write port"):
                self.mem.add_write_port("second")

    reset()
    Host()


def test_every_bank_is_dual_port_with_its_own_read_and_write_index():
    """1R1W per bank: a read and a write each have an index of their own, so a
    load in the same cycle as a store retiring still reads its own address."""
    config = rv32i_config(fe_lanes=4, commit_lanes=4)

    class Host(Module):
        @init
        def decl(self):
            self.mem = EasyMem(*config.instr_mem_spec())

    reset()
    mem   = Host().mem
    reads = mem.read_vary_index_4_phy_bank
    write = mem.write_vary_index_4_phy_bank

    assert len(reads) == len(write) == mem.bank_cnt
    assert all(r is not w for r, w in zip(reads, write))


def test_a_port_that_cannot_report_valid_is_refused():
    """A lane drops its word when the memory does not answer, so every port
    has to be able to say so."""
    config = rv32i_config(fe_lanes=1, commit_lanes=1)

    class Host(Module):
        @init
        def decl(self):
            self.mem = EasyMem(*config.instr_mem_spec())
            port     = self.mem.add_read_port("b0")
            plain    = MemPortRead(port.addr_meta, port.addr_srcs,
                                   port.pip_meta, port.timing, port.data)
            with pytest.raises(TypeError, match="MemPortReadValid"):
                Fetch(config, [plain])

    reset()
    Host()


def test_one_port_per_lane_is_required():
    config = rv32i_config(fe_lanes=2, commit_lanes=2)

    class Host(Module):
        @init
        def decl(self):
            self.mem = EasyMem(*config.instr_mem_spec())
            one      = [self.mem.add_read_port("b0")]
            with pytest.raises(ValueError, match="one instruction read port"):
                Fetch(config, one)

    reset()
    Host()
