# THE HOST DRIVER — the protocol a host runs against the HostBridge, written
# ONCE: hold reset, release it, prove the link, load both images, start, wait
# for the exit door, read the counters and the console back.
#
# It is written over two small abstract classes (bridge_driver_base.py), so the
# same code runs in three places:
#   WordPort   read / write one 32-bit word at a window address
#   ResetLine  hold / release the machine's mrst
# bridge_port_cocotb.py drives a simulated bridge, bridge_port_pynq.py the
# board, and tests/test_by_ai/test_bridge_driver.py a Python fake.
#
# `async` because cocotb must await clock edges; on the board and in the fake
# every method returns at once and asyncio.run() drives the coroutine.
#
# A wait is counted in POLLS, not wall-clock seconds: `timeout_s / poll_s` reads
# of STATUS. Under cocotb a poll is a fixed number of clock edges, so the same
# limit means the same thing in simulation and on the board.
#
# stdlib only: this file runs on the board.

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from .bridge_driver_base import (BridgeMismatch, HostRunOutcome, HostStatus, ResetLine, WordPort,
                                 interleave_banks)
from .bridge_map         import (CONSOLE_TAGS, CONSOLE_WORDS, CTRL_START, DMEM, IMEM, MAGIC_WORD,
                                 REG_CONSOLE_COUNT, REG_CTRL, REG_CYCLE_LIMIT, REG_CYCLES,
                                 REG_EXIT_CODE, REG_GEOMETRY, REG_MAGIC, REG_SCRATCH, REG_STATUS,
                                 HostMap)

STOP_EXIT       = "exit"           # the same words examples/sim uses
STOP_MAX_CYCLES = "max_cycles"
STOP_TIMEOUT    = "timeout"        # the host gave up; the machine may still be running

SCRATCH_PATTERN = 0x5A5AA5A5


# ---- the protocol -----------------------------------------------------------------------

class HostDriver:
    """Runs one program on a machine behind a HostBridge."""

    def __init__(self, port: WordPort, reset: ResetLine, host_map: HostMap) -> None:
        self.port     = port
        self.reset    = reset
        self.host_map = host_map

    # --- registers -------------------------------------------------------------
    async def read_reg (self, reg_offset: int) -> int:         return await self.port.read (self.host_map.reg_addr(reg_offset))
    async def write_reg(self, reg_offset: int, word: int) -> None: await self.port.write(self.host_map.reg_addr(reg_offset), word)

    async def read_status(self) -> HostStatus:
        return HostStatus.from_word(await self.read_reg(REG_STATUS))

    async def check_identity(self) -> None:
        """MAGIC, GEOMETRY and a SCRATCH round trip: the link works and the
        bitstream was built for THIS map."""
        magic = await self.read_reg(REG_MAGIC)
        if magic != MAGIC_WORD:
            raise BridgeMismatch(
                f"REG_MAGIC reads {magic:#010x}, expected {MAGIC_WORD:#010x} — no HostBridge "
                f"at this window, or the link is broken")
        geometry = await self.read_reg(REG_GEOMETRY)
        if geometry != self.host_map.geometry_word:
            raise BridgeMismatch(
                f"REG_GEOMETRY reads {geometry:#010x}, this map says "
                f"{self.host_map.geometry_word:#010x} — the bitstream was built for other "
                f"memory sizes")
        await self.write_reg(REG_SCRATCH, SCRATCH_PATTERN)
        scratch = await self.read_reg(REG_SCRATCH)
        if scratch != SCRATCH_PATTERN:
            raise BridgeMismatch(
                f"REG_SCRATCH reads back {scratch:#010x} after writing {SCRATCH_PATTERN:#010x}")

    # --- loading -----------------------------------------------------------------
    async def load_words(self, region: str, words: Sequence[int]) -> None:
        """Every word of an image, zeros included — the memories power up undefined."""
        for index, word in enumerate(words):
            await self.port.write(self.host_map.entry_addr(region, index), word)

    async def load_program(self, instr_banks: Sequence[Sequence[int]], data_words: Sequence[int]) -> None:
        await self.load_words(IMEM, interleave_banks(instr_banks))
        await self.load_words(DMEM, data_words)

    # --- running -------------------------------------------------------------------
    async def start(self, cycle_limit: int) -> None:
        await self.write_reg(REG_CYCLE_LIMIT, cycle_limit)
        await self.write_reg(REG_CTRL, CTRL_START)

    async def wait_finished(self, timeout_s: float, poll_s: float) -> Tuple[HostStatus, bool]:
        """(the last status read, timed out). Polls at most timeout_s / poll_s times."""
        max_polls = max(1, math.ceil(timeout_s / poll_s))
        status    = await self.read_status()
        for _ in range(max_polls):
            if status.finished:
                return status, False
            await self.port.pause(poll_s)
            status = await self.read_status()
        return status, not status.finished

    async def read_console(self, count: int) -> List[Tuple[int, int]]:
        entries = []
        for index in range(count):
            tag  = await self.port.read(self.host_map.entry_addr(CONSOLE_TAGS,  index))
            word = await self.port.read(self.host_map.entry_addr(CONSOLE_WORDS, index))
            entries.append((tag, word))
        return entries

    async def run_program(self,
                          instr_banks : Sequence[Sequence[int]],
                          data_words  : Sequence[int],
                          cycle_limit : int,
                          timeout_s   : float,
                          poll_s      : float = 1e-3) -> HostRunOutcome:
        """The whole protocol, in the order the hardware needs it.

        - reset first: the bridge and the read locks come up clean
        - the images go in while the locks are closed; START opens them
        """
        await self.reset.hold()
        await self.reset.release()
        await self.check_identity()
        await self.load_program(instr_banks, data_words)
        await self.start(cycle_limit)
        status, timed_out = await self.wait_finished(timeout_s, poll_s)

        count   = min(await self.read_reg(REG_CONSOLE_COUNT), self.host_map.console_depth)
        console = await self.read_console(count)
        cycles  = await self.read_reg(REG_CYCLES)
        if timed_out:
            stop_reason, exit_code = STOP_TIMEOUT, None
        elif status.exit_seen:
            stop_reason, exit_code = STOP_EXIT, await self.read_reg(REG_EXIT_CODE)
        else:
            stop_reason, exit_code = STOP_MAX_CYCLES, None
        return HostRunOutcome(stop_reason        = stop_reason,
                              cycles             = cycles,
                              exit_code          = exit_code,
                              console            = console,
                              console_overflow   = status.console_overflow,
                              host_write_refused = status.host_write_refused,
                              status_word        = status.word)
