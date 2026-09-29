# The HostBridge's window on the board: PYNQ's MMIO over the AXI BRAM controller
# in front of it, and an AXI GPIO bit as the machine's mrst. Runs on the board
# only — `pynq` exists nowhere else — under asyncio.run().
#
# Both blocks are found in the overlay BY CELL NAME (bridge_map.HOST_BRAM_CELL,
# RESET_GPIO_CELL), the names the Vivado build gives them, and their addresses
# come from the .hwh the overlay loaded — nothing here spells an address.

from __future__ import annotations

import asyncio

from pynq import MMIO, Overlay

from .bridge_driver import ResetLine, WordPort
from .bridge_map import HOST_BRAM_CELL, RESET_GPIO_CELL, HostMap

SETTLE_S = 1e-3            # after a reset edge, before the next access


class PynqWordPort(WordPort):
    """One MMIO word per access."""

    def __init__(self, mmio: MMIO) -> None:
        self.mmio = mmio

    async def read (self, addr: int) -> int:             return self.mmio.read(addr)
    async def write(self, addr: int, word: int) -> None: self.mmio.write(addr, word)
    async def pause(self, seconds: float) -> None:       await asyncio.sleep(seconds)


class AxiGpioResetLine(ResetLine):
    """Bit 0 of an all-output AXI GPIO channel, wired to the machine's mrst."""

    def __init__(self, channel, settle_s: float = SETTLE_S) -> None:
        self.channel  = channel
        self.settle_s = settle_s

    async def hold(self) -> None:
        self.channel.write(1, 0x1)
        await asyncio.sleep(self.settle_s)

    async def release(self) -> None:
        self.channel.write(0, 0x1)
        await asyncio.sleep(self.settle_s)


def open_board_ports(overlay: Overlay, host_map: HostMap):
    """(PynqWordPort, AxiGpioResetLine) for a loaded overlay built by examples/fpga."""
    if HOST_BRAM_CELL not in overlay.mem_dict:
        raise RuntimeError(
            f"the overlay has no memory '{HOST_BRAM_CELL}' — is this an examples/fpga bitstream? "
            f"memories: {sorted(overlay.mem_dict)}")
    base = overlay.mem_dict[HOST_BRAM_CELL]["phys_addr"]
    port = PynqWordPort(MMIO(base, host_map.window_bytes))
    gpio = getattr(overlay, RESET_GPIO_CELL)
    return port, AxiGpioResetLine(gpio.channel1)
