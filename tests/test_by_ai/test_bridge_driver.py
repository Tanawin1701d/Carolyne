# The host driver against a Python model of the bridge's registers. What is
# pinned is the ORDER of the protocol (reset, identity, load, start, wait, read)
# and the three ways a run ends.

from __future__ import annotations

import asyncio

import pytest

from examples.fpga.bridge import (CONSOLE_TAGS, CONSOLE_WORDS, CTRL_START, DMEM, IMEM, MAGIC_WORD,
                                  REG_CONSOLE_COUNT, REG_CTRL, REG_CYCLE_LIMIT, REG_CYCLES,
                                  REG_EXIT_CODE, REG_GEOMETRY, REG_MAGIC, REG_SCRATCH, REG_STATUS,
                                  STATUS_CYCLE_LIMIT_HIT, STATUS_EXIT_SEEN, STATUS_FINISHED,
                                  STATUS_STARTED, STOP_EXIT, STOP_MAX_CYCLES, STOP_TIMEOUT,
                                  TAG_PUTCHAR, TAG_PUTINT, BridgeMismatch, HostDriver, HostMap,
                                  HostRunOutcome, ResetLine, WordPort, read_bridge_run_spec,
                                  write_bridge_run_spec)
from examples.fpga.bridge.bridge_run_spec import BridgeRunSpec

DOORS = {"putchar": 1020, "putint": 1021, "exit": 1022}
MAP   = HostMap(8192, 2, 4096, 16, DOORS)


class FakeBridgePort(WordPort):
    """The registers as software: finishes `finish_after` polls after START."""

    def __init__(self, host_map: HostMap, finish_after: int = 2, exit_code=7,
                 console=((TAG_PUTCHAR, ord("h")), (TAG_PUTINT, 0xFFFFFFFF)),
                 magic=MAGIC_WORD, geometry=None, finish_by_limit=False) -> None:
        self.host_map        = host_map
        self.finish_after    = finish_after
        self.exit_code       = exit_code
        self.console         = list(console)
        self.magic           = magic
        self.geometry        = host_map.geometry_word if geometry is None else geometry
        self.finish_by_limit = finish_by_limit
        self.regs            = {REG_SCRATCH: 0, REG_CYCLE_LIMIT: 0}
        self.memory          = {IMEM: {}, DMEM: {}}
        self.log             = []                 # every write, in order
        self.polls_left      = None               # None until START

    async def read(self, addr: int) -> int:
        region, offset = self.host_map.region_of(addr)
        if region == CONSOLE_WORDS: return self.console[offset // 4][1]
        if region == CONSOLE_TAGS:  return self.console[offset // 4][0]
        assert region == "regs"
        if offset == REG_MAGIC:         return self.magic
        if offset == REG_GEOMETRY:      return self.geometry
        if offset == REG_STATUS:        return self._status()
        if offset == REG_CYCLES:        return 244
        if offset == REG_EXIT_CODE:     return self.exit_code
        if offset == REG_CONSOLE_COUNT: return len(self.console)
        return self.regs[offset]

    async def write(self, addr: int, word: int) -> None:
        region, offset = self.host_map.region_of(addr)
        self.log.append((region, offset, word))
        if region in self.memory:
            self.memory[region][offset // 4] = word
        elif offset == REG_CTRL and word & CTRL_START:
            self.polls_left = self.finish_after
        else:
            self.regs[offset] = word

    async def pause(self, seconds: float) -> None:
        if self.polls_left is not None and self.polls_left > 0:
            self.polls_left -= 1

    def _status(self) -> int:
        if self.polls_left is None:
            return 0
        if self.polls_left > 0:
            return STATUS_STARTED
        done = STATUS_CYCLE_LIMIT_HIT if self.finish_by_limit else STATUS_EXIT_SEEN
        return STATUS_STARTED | STATUS_FINISHED | done


class FakeResetLine(ResetLine):
    def __init__(self, log) -> None: self.log = log
    async def hold   (self) -> None: self.log.append(("reset", "hold", 1))
    async def release(self) -> None: self.log.append(("reset", "release", 0))


BANKS = [[0x11, 0x22, 0x00], [0x33, 0x44, 0x55]]
DATA  = [0xA, 0x0, 0xB]


def run(port: FakeBridgePort, **kwargs) -> HostRunOutcome:
    driver = HostDriver(port, FakeResetLine(port.log), MAP)
    return asyncio.run(driver.run_program(BANKS, DATA, cycle_limit=kwargs.pop("cycle_limit", 0),
                                          timeout_s=kwargs.pop("timeout_s", 1.0),
                                          poll_s=kwargs.pop("poll_s", 0.1)))


def test_the_protocol_runs_in_order_and_writes_every_word():
    port    = FakeBridgePort(MAP)
    outcome = run(port, cycle_limit=5000)
    kinds   = [entry[:2] if entry[0] == "reset" else entry[0] for entry in port.log]
    # reset, then the scratch test, then imem, dmem, then the limit and START
    assert kinds[:2] == [("reset", "hold"), ("reset", "release")]
    assert kinds[2]  == "regs" and port.log[2][1] == REG_SCRATCH
    assert kinds[3:9]   == [IMEM] * 6
    assert kinds[9:12]  == [DMEM] * 3
    assert port.log[12] == ("regs", REG_CYCLE_LIMIT, 5000)
    assert port.log[13] == ("regs", REG_CTRL, CTRL_START)
    # the interleaved image, zeros included
    assert port.memory[IMEM] == {0: 0x11, 1: 0x33, 2: 0x22, 3: 0x44, 4: 0x00, 5: 0x55}
    assert port.memory[DMEM] == {0: 0xA, 1: 0x0, 2: 0xB}
    assert outcome.stop_reason == STOP_EXIT
    assert outcome.exit_code   == 7
    assert outcome.cycles      == 244
    assert outcome.console     == [(TAG_PUTCHAR, ord("h")), (TAG_PUTINT, 0xFFFFFFFF)]
    assert outcome.status_word & STATUS_EXIT_SEEN


def test_a_cycle_limit_stop_has_no_exit_code():
    outcome = run(FakeBridgePort(MAP, finish_by_limit=True))
    assert outcome.stop_reason == STOP_MAX_CYCLES
    assert outcome.exit_code is None


def test_the_host_gives_up_after_timeout_s_over_poll_s_polls():
    outcome = run(FakeBridgePort(MAP, finish_after=50), timeout_s=1.0, poll_s=0.1)
    assert outcome.stop_reason == STOP_TIMEOUT
    assert outcome.exit_code is None
    assert run(FakeBridgePort(MAP, finish_after=9), timeout_s=1.0, poll_s=0.1).stop_reason == STOP_EXIT


def test_a_wrong_bridge_is_refused_before_anything_is_loaded():
    with pytest.raises(BridgeMismatch, match="REG_MAGIC"):
        run(FakeBridgePort(MAP, magic=0))
    port = FakeBridgePort(MAP, geometry=0x12345678)
    with pytest.raises(BridgeMismatch, match="other memory sizes"):
        run(port)
    assert not port.memory[IMEM] and not port.memory[DMEM]


def test_the_outcome_survives_json():
    outcome = run(FakeBridgePort(MAP))
    assert HostRunOutcome.from_dict(outcome.to_dict()) == outcome


def test_the_run_spec_keeps_its_paths_relative_to_itself(tmp_path):
    images = tmp_path / "program"
    images.mkdir()
    for name in ("imem_bank0.hex", "imem_bank1.hex", "dmem.hex"):
        (images / name).write_text("00000000\n")
    spec = BridgeRunSpec(name="hello", host_map=MAP.to_dict(),
                         instr_hex=[str(images / "imem_bank0.hex"), str(images / "imem_bank1.hex")],
                         data_hex=str(images / "dmem.hex"), cycle_limit=0, timeout_s=10.0)
    path = tmp_path / "bridge_run_spec.json"
    write_bridge_run_spec(str(path), spec)
    assert '"program/imem_bank0.hex"' in path.read_text()      # relative in the file
    back = read_bridge_run_spec(str(path))
    assert back == spec                                          # absolute again when read
    assert HostMap.from_dict(back.host_map) == MAP
