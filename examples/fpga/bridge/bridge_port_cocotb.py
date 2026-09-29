# The HostBridge's window driven from a cocotb test: the same HostDriver the
# board runs, over the simulated top's host_* ports. One access per clock edge;
# a read's answer is sampled one edge after it was asked (READ_LATENCY 1).
#
# `pause` waits CLOCK EDGES, not seconds: the driver polls in fixed steps, so a
# timeout is a number of polls and means the same thing here and on the board.

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from .bridge_driver import ResetLine, WordPort
from .bridge_map import HOST_ADDR, HOST_EN, HOST_RDATA, HOST_WDATA, HOST_WE

CLOCK_NS    = 10
WORD_ENABLE = 0xF          # every byte of the word


def start_clock(dut, period_ns: int = CLOCK_NS) -> None:
    cocotb.start_soon(Clock(dut.clk, period_ns, unit="ns").start())


class CocotbWordPort(WordPort):
    """host_* driven for one edge per access."""

    def __init__(self, dut, poll_cycles: int = 64) -> None:
        self.dut         = dut
        self.poll_cycles = poll_cycles
        self.en          = getattr(dut, HOST_EN)
        self.we          = getattr(dut, HOST_WE)
        self.addr        = getattr(dut, HOST_ADDR)
        self.wdata       = getattr(dut, HOST_WDATA)
        self.rdata       = getattr(dut, HOST_RDATA)
        self.idle()

    def idle(self) -> None:
        self.en.value, self.we.value, self.addr.value, self.wdata.value = 0, 0, 0, 0

    async def write(self, addr: int, word: int) -> None:
        self.en.value, self.we.value, self.addr.value, self.wdata.value = 1, WORD_ENABLE, addr, word
        await RisingEdge(self.dut.clk)
        await Timer(1, unit="ns")
        self.idle()

    async def read(self, addr: int) -> int:
        self.en.value, self.we.value, self.addr.value = 1, 0, addr
        await RisingEdge(self.dut.clk)             # rdata_reg takes the answer here
        await Timer(1, unit="ns")
        self.idle()
        value = self.rdata.value
        if not value.is_resolvable:
            raise ValueError(f"CocotbWordPort: {HOST_RDATA} reads X after a read at {addr:#x}")
        return int(value)

    async def pause(self, seconds: float) -> None:
        for _ in range(self.poll_cycles):
            await RisingEdge(self.dut.clk)


class CocotbResetLine(ResetLine):
    """mrst held for a few edges, then released — the sim harness's own order."""

    def __init__(self, dut, reset_cycles: int = 3) -> None:
        self.dut          = dut
        self.reset_cycles = reset_cycles

    async def hold(self) -> None:
        self.dut.mrst.value = 1
        for _ in range(self.reset_cycles):
            await RisingEdge(self.dut.clk)

    async def release(self) -> None:
        await Timer(1, unit="ns")
        self.dut.mrst.value = 0
        await RisingEdge(self.dut.clk)
        await Timer(1, unit="ns")
