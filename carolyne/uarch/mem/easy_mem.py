# EASY MEM — banked storage that answers in the cycle it is asked.
#
# TODO: NOT REVIEWED. The bank routing here — the read crossbar, the conflict
# rule that drives `valid`, and the write enable — was rewritten as dual-port
# banks on 2026-09-10 and has only been ELABORATED and compiled. No test has
# run a single cycle of it, so nothing has yet shown that a port reads the bank
# it named or that a loser reports 0. Read it before trusting it.
#
# THE BANK IS PART OF THE ADDRESS, not part of the port. A port names a bank
# per access, so a requestor states one address and this memory routes it:
#
#   | index | bank | zero |      AddrMeta's regions, high first
#
# EACH BANK IS DUAL PORT — one read and one write a cycle, each with its own
# index — so a read and a write never conflict. Two READ ports naming one bank
# do: the lower-numbered one is served and the other's `valid` reads 0. There
# is ONE write port, and it reaches every bank, so writes never conflict.
#
# A port is built WHEN IT IS ASKED FOR — there is no port count. A requestor
# calls add_read_port / add_write_port at any time and gets back the wires it
# drives; MemBase.own_scope puts the hardware in this module whatever scope the
# caller is in, and Kathryn wires the crossing automatically.
#
# A WRITE port's PipCon is no_pip_master(): the memory is never busy for one.
#
# A READ port's is mastered by `read_ready` — THE READ LOCK — which powers up
# 0, so no read is granted until something releases it and a core fetching
# through it does not start. Writes stay open, which is what lets an outside
# agent fill the memory first and release the reads afterwards.

from __future__ import annotations

from typing import Optional, Tuple

from kathryn import (Module, PipCon, flow, init, mem_blk, mem_ele, mux, reg,
                     val, wire, zif)

from carolyne.uarch.common.hw_util import ceil_log2
from carolyne.uarch.mem.common.addr_meta import AddrMeta
from carolyne.uarch.mem.common.mem_base import MemBase
from carolyne.uarch.mem.common.mem_port import (MemPortReadValid, MemPortWrite,
                                                PortTiming)
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
        self.bank_bits   = ceil_log2(bank_cnt)

        self._reads        = []     # per read port: its wires, for the routing
        self._writes       = []     # per write port: the same
        self._read_release = None   # the condition release_read_on() bound

        # One bank means nothing to select, so the address states no bank
        # region at all — a zero-width one would need a zero-width wire.
        regions = ((index_width,) if self.bank_cnt == 1
                   else (index_width, self.bank_bits))
        super().__init__(AddrMeta(regions, ceil_log2(data_bus_bytes)))

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
        self.banks = [mem_blk(data_bits, self.index_width, f"bank{bank_id}")
                      for bank_id in range(self.bank_cnt)]

        # DUAL PORT per bank: the read and the write each get their own index,
        # driven by the routing, so each is a wire the element follows.
        self.read_vary_index_4_phy_bank  = [
            wire(self.index_width, f"read_vary_index_4_phy_bank{bank_id}")
            for bank_id in range(self.bank_cnt)]
        self.write_vary_index_4_phy_bank = [
            wire(self.index_width, f"write_vary_index_4_phy_bank{bank_id}")
            for bank_id in range(self.bank_cnt)]

        self.bank_data  = [mem_ele(self.banks[bank_id],
                                   self.read_vary_index_4_phy_bank[bank_id],
                                   data_bits, True, f"bank{bank_id}_out")
                           for bank_id in range(self.bank_cnt)]
        self.bank_write = [mem_ele(self.banks[bank_id],
                                   self.write_vary_index_4_phy_bank[bank_id],
                                   data_bits, False, f"bank{bank_id}_in")
                           for bank_id in range(self.bank_cnt)]

        # THE READ LOCK. Reset 0 = locked, so nothing reads until released.
        self.read_ready = reg(1, "read_ready")
        self.read_ready.reset(0)

    def release_read_on(self, condition) -> None:
        """Let hardware release the read lock, instead of a testbench poke.

        Set once: the lock is one-way, so two releases would be two answers.
        """
        if self._read_release is not None:
            raise ValueError(
                "EasyMem: the read lock already has a release condition")
        self._read_release = condition

    # --- ports ---------------------------------------------------------------

    def gen_read_port(self, name: Optional[str] = None) -> MemPortReadValid:
        """One read port: address in, data and validity out the same cycle."""
        label          = name or f"rd{len(self.read_ports)}"
        parts          = self._gen_port_parts(label)
        parts["data"]  = wire(self.addr_meta.data_bus_bits, f"{label}_data")
        parts["valid"] = wire(1, f"{label}_valid")
        self._reads.append(parts)

        # The LOCK masters this arb, so a read is granted only once released.
        parts["meta"].set_master_ack(self.read_ready)
        return MemPortReadValid(self.addr_meta,
                                parts["addr"],
                                parts["meta"],
                                PortTiming.LEVEL,
                                parts["data"],
                                parts["valid"])

    def gen_write_port(self, name: Optional[str] = None) -> MemPortWrite:
        """One write port: taken this cycle, landing on the edge.

        Only ONE. Each bank has one write port and this one reaches every
        bank, so a second could name the same bank — and a dropped write is
        lost data, where a dropped read is only a stalled requestor.
        """
        self._reject_second_writer(name)
        label           = name or f"wr{len(self.write_ports)}"
        parts           = self._gen_port_parts(label)
        parts["data"]   = wire(self.addr_meta.data_bus_bits, f"{label}_data")
        parts["enable"] = wire(1, f"{label}_en")
        self._writes.append(parts)

        # A write is never locked: filling the memory is what the lock is for.
        parts["meta"].no_pip_master()
        # NEXT_EDGE: the request is taken this cycle, the value lands at the edge.
        return MemPortWrite(self.addr_meta,
                            parts["addr"],
                            parts["meta"],
                            PortTiming.NEXT_EDGE,
                            parts["data"],
                            parts["enable"])

    def _reject_second_writer(self, name) -> None:
        if self.write_ports:
            raise ValueError(
                f"EasyMem: takes ONE write port — each bank has one, and this "
                f"port already reaches every bank — and '{name}' would be the "
                f"second")

    def _gen_port_parts(self, label: str) -> dict:
        # What every port gathers: one address wire per region, and a bare
        # arbiter. WHO masters it is the caller's choice — a write ties the
        # ack to 1, a read gives it to the lock.
        index = wire(self.index_width, f"{label}_index")
        addr  = (index,)
        bank  = None
        if self.bank_cnt > 1:
            bank = wire(self.bank_bits, f"{label}_bank")
            addr = (index, bank)
        return {"index": index, "bank": bank, "addr": addr, "meta": PipCon()}

    # --- the routing ---------------------------------------------------------

    @flow
    def route_access(self):
        """Drive each bank's read and write port, then answer every read."""
        if self._read_release is not None:
            with zif(self._read_release):
                self.read_ready |= 1

        # Every wire has ONE driver — two would resolve by priority, not by
        # statement order — so the loops split by wire: banks, then read ports.
        for bank_id in range(self.bank_cnt):     # address: port -> bank
            self._drive_read_vary_index_4_phy_bank(bank_id)
            self._drive_bank_write(bank_id)
        for port in self._reads:                 # data:    bank -> port
            self._drive_read_answer(port)

    def _match_bank(self, port: dict, bank_id: int):
        """1 when the port's bank field is `bank_id`; always 1 if unbanked."""
        if port["bank"] is None:
            return val(1, 1)
        return port["bank"] == bank_id

    def _drive_read_vary_index_4_phy_bank(self, bank_id: int) -> None:
        # The bank's read port takes the index of the LOWEST-numbered read that
        # named it: the mux chain is built from the top down, so that read is
        # the outermost mux.
        chosen = None
        for port in reversed(self._reads):
            chosen = (port["index"] if chosen is None
                      else mux(self._match_bank(port, bank_id),
                               port["index"], chosen))
        if chosen is not None:
            self.read_vary_index_4_phy_bank[bank_id] *= chosen

    def _drive_bank_write(self, bank_id: int) -> None:
        """The bank's write port: the writer's index, and its data when it
        named this bank."""
        if not self._writes:
            return
        writer = self._writes[0]                    # there is only ever one
        self.write_vary_index_4_phy_bank[bank_id] *= writer["index"]
        with zif(self._match_bank(writer, bank_id) & writer["enable"]):
            self.bank_write[bank_id] |= writer["data"]

    def _drive_read_answer(self, port: dict) -> None:
        # The port reads back the bank it named.
        picked = self.bank_data[0]
        for bank_id in range(1, self.bank_cnt):
            picked = mux(self._match_bank(port, bank_id),
                         self.bank_data[bank_id], picked)
        port["data"] *= picked

        # A bank's read port serves ONE read a cycle, so this read is invalid
        # when a lower-numbered read named the same bank. A write never blocks
        # it: the write has a port of its own.
        blocked = None
        for other in self._reads:
            if other is port:
                break
            blocked = self._or(blocked, self._same_bank(port, other))
        port["valid"] *= val(1, 1) if blocked is None else ~blocked

    @staticmethod
    def _or(acc, term):
        return term if acc is None else (acc | term)

    def _same_bank(self, port: dict, other: dict):
        if port["bank"] is None:
            return val(1, 1)                # one bank: everyone collides
        return port["bank"] == other["bank"]
