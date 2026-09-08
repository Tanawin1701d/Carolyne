# EASY MEM — banked storage that answers in the cycle it is asked.
#
# A port names its BANK at elaboration time, so the bank is not part of the
# address: the address is | index | zero | and every bank holds its own
# independent image. There is no crossbar and no bank arbitration, which is
# what keeps the access one cycle wide.
#
# A port is built WHEN IT IS ASKED FOR — there is no port count. A requestor
# calls add_read_port / add_write_port at any time and gets back the wires it
# drives; MemBase.own_scope puts the hardware in this module whatever scope the
# caller is in, and Kathryn wires the crossing automatically. Each port carries
# its whole access with it, so nothing here waits for a later @flow.
#
# THE MEMORY BUILDS NO LOGIC. A port's `data` IS the memory element: a read port
# hands out the read node and the requestor reads it, a write port hands out the
# write node and the requestor drives it. So the access is gated by the
# requestor's own scope — a write inside its zync fires on that grant — and this
# module states no condition of its own.
#
# Each port's PipCon is no_pip_master(), so a requestor's zync is granted the
# moment it wins arbitration: the memory is never busy.

from __future__ import annotations

from typing import Optional, Tuple

from kathryn import Module, PipCon, init, mem_blk, mem_ele, wire

from carolyne.uarch.common.hw_util import ceil_log2
from carolyne.uarch.mem.common.addr_meta import AddrMeta
from carolyne.uarch.mem.common.mem_base import MemBase
from carolyne.uarch.mem.common.mem_port import MemPortRead, MemPortWrite, PortTiming
from carolyne.util.bit_checking import is_power_of_two


class EasyMem(MemBase):
    """Banked storage with same-cycle read and write ports."""

    def __init__(self,
                 index_width    : int,
                 bank_cnt       : int,
                 data_bus_bytes : int):
        # Plain-Python configuration BEFORE super().__init__(): that call runs
        # com_declare, which builds the banks from these.
        self._reject_bad_size(index_width, bank_cnt, data_bus_bytes)
        self.index_width = index_width
        self.bank_cnt    = bank_cnt
        self._write_bank = {}       # bank -> the one port that writes it
        super().__init__(AddrMeta((index_width,), ceil_log2(data_bus_bytes)))

    @staticmethod
    def _reject_bad_size(index_width, bank_cnt, data_bus_bytes) -> None:
        # Sizes only — the address shape itself is AddrMeta's to check.
        if index_width < 1:
            raise ValueError(f"EasyMem: index_width must be >= 1, got {index_width}")
        if not is_power_of_two(bank_cnt):
            raise ValueError(f"EasyMem: bank_cnt must be a power of two, got {bank_cnt}")
        if not is_power_of_two(data_bus_bytes):
            raise ValueError(
                f"EasyMem: data_bus_bytes must be a power of two, got {data_bus_bytes}")

    # --- declaration ---------------------------------------------------------

    @init
    def com_declare(self):
        data_bits  = self.addr_meta.data_bus_bits
        self.banks = [mem_blk(data_bits, self.index_width, f"bank{k}")
                      for k in range(self.bank_cnt)]

    def gen_read_port(self, bank: int, name: Optional[str] = None) -> MemPortRead:
        """One read port on one bank: address in, data out in the same cycle."""
        label = name or f"rd{len(self.read_ports)}"
        index, meta = self._gen_port_parts(label)
        # The read element IS the port's data: a copy into a wire would need an
        # assign, and an assign needs a top module, which does not exist while a
        # requestor's @init runs.
        data = mem_ele(self._bank(bank, label), index,
                       self.addr_meta.data_bus_bits, True, f"{label}_data")
        return MemPortRead(self.addr_meta, (index,), meta, PortTiming.LEVEL, data)

    def gen_write_port(self, bank: int, name: Optional[str] = None) -> MemPortWrite:
        """One write port on one bank: taken this cycle, landing on the edge."""
        label = name or f"wr{len(self.write_ports)}"
        self._claim_write_bank(bank, label)
        index, meta = self._gen_port_parts(label)
        # The write element IS the port's data. Driving it is the requestor's
        # own statement, so the write fires on the requestor's grant and this
        # memory needs no enable of its own.
        data = mem_ele(self._bank(bank, label), index,
                       self.addr_meta.data_bus_bits, False, f"{label}_data")
        # NEXT_EDGE: a memory element takes the clocked assign and no other, so
        # the request is taken this cycle and the value lands at the edge.
        return MemPortWrite(self.addr_meta, (index,), meta, PortTiming.NEXT_EDGE, data)

    # --- the parts a port gathers --------------------------------------------

    def _gen_port_parts(self, label: str) -> Tuple[object, PipCon]:
        # What every port gathers: the index wire the requestor drives, and an
        # arbiter nothing masters.
        index = wire(self.index_width, f"{label}_index")
        meta  = PipCon()
        meta.no_pip_master()        # the memory always serves: ack mirrors req
        return index, meta

    def _bank(self, bank: int, where: str):
        if isinstance(bank, bool) or not isinstance(bank, int):
            raise ValueError(f"EasyMem {where}: bank must be an int, got {type(bank).__name__}")
        if not 0 <= bank < self.bank_cnt:
            raise ValueError(
                f"EasyMem {where}: bank {bank} outside 0..{self.bank_cnt - 1}")
        return self.banks[bank]

    def _claim_write_bank(self, bank: int, where: str) -> None:
        # One writer per bank: two write ports would be two clocked drivers of
        # one memory array, which is a race in simulation and illegal in synthesis.
        self._bank(bank, where)
        if bank in self._write_bank:
            raise ValueError(
                f"EasyMem {where}: bank {bank} is already written by "
                f"'{self._write_bank[bank]}'")
        self._write_bank[bank] = where
