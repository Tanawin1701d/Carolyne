# HostBridge — the hardware a host reaches the machine through: one window of
# byte addresses (bridge_map.py) on five top-level ports, shaped like the BRAM
# side of an AXI BRAM controller.
#
#   host_en, host_we[3:0], host_addr[addr_bits-1:0], host_wdata[31:0]   in
#   host_rdata[31:0]                                                     out, one cycle after host_en
#
# What it does with the window:
#   REGS            MAGIC / GEOMETRY / STATUS / CYCLES / EXIT_CODE / CONSOLE_COUNT read back;
#                   CTRL.START releases both memories' read locks; CYCLE_LIMIT and SCRATCH are plain registers
#   CONSOLE_*       what the program printed: the bridge SNOOPS the core's store port and
#                   captures every store to the putchar / putint door, with its tag
#   IMEM / DMEM     a write lands in the memory through EasyMem's host write port
#                   (honoured only while the read lock is closed)
#
# The exit door ends the run: EXIT_SEEN, EXIT_CODE, and the cycle counter stops.
# CYCLES counts clock edges from the lock release up to the edge that carries
# the exit store, which is the count the simulator's harness reports.
#
# Word writes only: any non-zero host_we is a whole word (PYNQ's MMIO.write is).
# Addresses in no region read 0 and take no write.

from __future__ import annotations

from typing import Dict

from kathryn import Module, flow, init, mem_blk, mem_ele, mux, reg, val, wire, zif

from carolyne.uarch.mem.common.mem_port import MemPortWrite
from carolyne.uarch.mem.easy_mem import EasyMem

from .bridge_map import (CONSOLE_TAGS, CONSOLE_WORDS, CTRL_START, DMEM, HOST_ADDR, HOST_EN,
                         HOST_RDATA, HOST_WDATA, HOST_WE, IMEM, MAGIC_WORD, REG_CONSOLE_COUNT,
                         REG_CTRL, REG_CYCLE_LIMIT, REG_CYCLES, REG_EXIT_CODE, REG_GEOMETRY,
                         REG_MAGIC, REG_SCRATCH, REG_STATUS, REGS, STATUS_CONSOLE_OVERFLOW,
                         STATUS_CYCLE_LIMIT_HIT, STATUS_EXIT_SEEN, STATUS_FINISHED,
                         STATUS_HOST_WRITE_REFUSED, STATUS_STARTED, HostMap, log2_exact)

WORD_BITS  = 32
REG_IDX_HI = 7            # register index = host_addr[7:2]: 64 word slots, 9 used


def memory_bytes(memory: EasyMem) -> int:
    return (1 << memory.index_width) * memory.bank_cnt * (memory.addr_meta.data_bus_bits // 8)


class HostBridge(Module):
    """The host's window into the machine: registers, console capture, image loading."""

    def __init__(self,
                 host_map   : HostMap,
                 instr_mem  : EasyMem,
                 data_mem   : EasyMem,
                 store_port : MemPortWrite,
                 name       : str = "host_bridge"):
        # Plain-Python configuration BEFORE super().__init__(): that call runs
        # com_declare, which builds from these.
        self.host_map   = host_map
        self.instr_mem  = instr_mem
        self.data_mem   = data_mem
        self.store_port = store_port
        self._reject_mismatch()
        super().__init__(name)

    def _reject_mismatch(self) -> None:
        """The map must describe THESE memories, or the host loads the wrong words."""
        if self.data_mem.addr_meta.data_bus_bits != WORD_BITS:
            raise ValueError(
                f"HostBridge: the data bus is {self.data_mem.addr_meta.data_bus_bits} bits, "
                f"the bridge is a {WORD_BITS}-bit window")
        for what, memory, want in (("imem_bytes", self.instr_mem, self.host_map.imem_bytes),
                                   ("dmem_bytes", self.data_mem,  self.host_map.dmem_bytes)):
            if memory_bytes(memory) != want:
                raise ValueError(
                    f"HostBridge: host_map.{what} is {want}, the memory holds {memory_bytes(memory)}")
        if self.instr_mem.bank_cnt != self.host_map.imem_banks:
            raise ValueError(
                f"HostBridge: host_map.imem_banks is {self.host_map.imem_banks}, "
                f"the memory has {self.instr_mem.bank_cnt}")
        if len(self.store_port.addr_srcs) != 1:
            raise ValueError("HostBridge: the store port must address ONE bank (the data memory's)")

    # --- declaration -----------------------------------------------------------------
    @init
    def com_declare(self):
        hm         = self.host_map
        depth_bits = log2_exact(hm.console_depth)

        # the window, as top-level ports
        self.host_en    = wire(1,            HOST_EN)   .mark_input (HOST_EN)
        self.host_we    = wire(4,            HOST_WE)   .mark_input (HOST_WE)
        self.host_addr  = wire(hm.addr_bits, HOST_ADDR) .mark_input (HOST_ADDR)
        self.host_wdata = wire(WORD_BITS,    HOST_WDATA).mark_input (HOST_WDATA)
        self.host_rdata = wire(WORD_BITS,    HOST_RDATA).mark_output(HOST_RDATA)
        self.rdata_reg  = reg(WORD_BITS, "rdata_reg")          # READ_LATENCY 1

        # the run
        self.start_pulse     = wire(1, "start_pulse")           # CTRL.START, this cycle
        self.exit_seen       = reg(1, "exit_seen")
        self.cycle_limit_hit = reg(1, "cycle_limit_hit")
        self.finished        = wire(1, "finished")
        self.running         = wire(1, "running")
        self.exit_code       = reg(WORD_BITS, "exit_code")
        self.cycles          = reg(WORD_BITS, "cycles")
        self.cycle_limit     = reg(WORD_BITS, "cycle_limit")
        self.scratch         = reg(WORD_BITS, "scratch")
        self.status          = wire(WORD_BITS, "status")
        for r in (self.exit_seen, self.cycle_limit_hit, self.exit_code,
                  self.cycles, self.cycle_limit, self.scratch):
            r.reset(0)

        # the console capture: entry i = (tag, word); count saturates at the depth
        self.console_count    = reg(depth_bits + 1, "console_count")
        self.console_count.reset(0)
        self.console_overflow = reg(1, "console_overflow")
        self.console_overflow.reset(0)
        self.console_words    = mem_blk(WORD_BITS, depth_bits, "console_words")
        self.console_tags     = mem_blk(1,         depth_bits, "console_tags")
        self.console_wr_idx   = wire(depth_bits, "console_wr_idx")
        self.console_rd_idx   = wire(depth_bits, "console_rd_idx")
        self.console_words_w  = mem_ele(self.console_words, self.console_wr_idx, WORD_BITS, False, "console_words_w")
        self.console_tags_w   = mem_ele(self.console_tags,  self.console_wr_idx, 1,         False, "console_tags_w")
        self.console_words_r  = mem_ele(self.console_words, self.console_rd_idx, WORD_BITS, True,  "console_words_r")
        self.console_tags_r   = mem_ele(self.console_tags,  self.console_rd_idx, 1,         True,  "console_tags_r")

        # the way into the memories, and the lock release START drives
        self.imem_write = self.instr_mem.add_host_write_port("host")
        self.dmem_write = self.data_mem .add_host_write_port("host")
        self.instr_mem.release_read_on(self.start_pulse)
        self.data_mem .release_read_on(self.start_pulse)

    # --- the flow ---------------------------------------------------------------------
    @flow
    def route_host(self):
        hm         = self.host_map
        write_now  = self.host_en & (self.host_we != 0)
        select     = self._region_selects()
        reg_idx    = self.host_addr[REG_IDX_HI, 2]
        reg_write  = {offset: write_now & select[REGS] & (reg_idx == offset >> 2)
                      for offset in (REG_CTRL, REG_CYCLE_LIMIT, REG_SCRATCH)}

        # --- registers a host writes
        self.start_pulse *= reg_write[REG_CTRL] & self.host_wdata[0, 0]      # CTRL_START is bit 0
        with zif(reg_write[REG_CYCLE_LIMIT]):
            self.cycle_limit |= self.host_wdata
        with zif(reg_write[REG_SCRATCH]):
            self.scratch |= self.host_wdata

        # --- the images: EasyMem routes a flat byte offset to its bank
        self.imem_write.bind_byte_addr(self.host_addr)
        self.dmem_write.bind_byte_addr(self.host_addr)
        with zif(write_now & select[IMEM]):
            self.imem_write.write(self.host_wdata)
        with zif(write_now & select[DMEM]):
            self.dmem_write.write(self.host_wdata)

        # --- the run: the store port, watched for the doors
        store_idx   = self.store_port.addr_srcs[0]
        store_hit   = lambda door: self.store_port.enable & (store_idx == hm.doors[door])
        hit_exit    = store_hit("exit")
        hit_putchar = store_hit("putchar")
        hit_putint  = store_hit("putint")

        self.finished *= self.exit_seen | self.cycle_limit_hit
        self.running  *= self.data_mem.read_ready & ~self.finished
        with zif(self.running & hit_exit):
            self.exit_seen |= 1
            self.exit_code |= self.store_port.data
        # not on the edge that carries the exit store: that edge is the one the
        # harness sees the store on and stops counting at
        with zif(self.running & ~hit_exit):
            self.cycles |= self.cycles + 1
        with zif(self.running & (self.cycle_limit != 0) & (self.cycles == self.cycle_limit)):
            self.cycle_limit_hit |= 1

        # --- the console capture
        depth_bits            = log2_exact(hm.console_depth)
        console_full          = self.console_count[depth_bits, depth_bits]
        console_hit           = self.running & (hit_putchar | hit_putint)
        self.console_wr_idx  *= self.console_count[depth_bits - 1, 0]
        with zif(console_hit & ~console_full):
            self.console_words_w |= self.store_port.data
            self.console_tags_w  |= hit_putint
            self.console_count   |= self.console_count + 1
        with zif(console_hit & console_full):
            self.console_overflow |= 1

        # --- what a host reads back, one cycle later
        self._drive_status()
        self.console_rd_idx *= self.host_addr[depth_bits + 1, 2]
        readable = ((select[REGS] & (reg_idx == REG_MAGIC         >> 2), val(WORD_BITS, MAGIC_WORD)),
                    (select[REGS] & (reg_idx == REG_GEOMETRY      >> 2), val(WORD_BITS, hm.geometry_word)),
                    (select[REGS] & (reg_idx == REG_STATUS        >> 2), self.status),
                    (select[REGS] & (reg_idx == REG_CYCLES        >> 2), self.cycles),
                    (select[REGS] & (reg_idx == REG_EXIT_CODE     >> 2), self.exit_code),
                    (select[REGS] & (reg_idx == REG_CONSOLE_COUNT >> 2), self.console_count),
                    (select[REGS] & (reg_idx == REG_CYCLE_LIMIT   >> 2), self.cycle_limit),
                    (select[REGS] & (reg_idx == REG_SCRATCH       >> 2), self.scratch),
                    (select[CONSOLE_WORDS],                              self.console_words_r),
                    (select[CONSOLE_TAGS],                               self.console_tags_r))
        picked = val(WORD_BITS, 0)
        for cond, value in readable:
            picked = mux(cond, value, picked, width=WORD_BITS)
        self.rdata_reg  |= picked
        self.host_rdata *= self.rdata_reg

    def _region_selects(self) -> Dict[str, object]:
        """One 1-bit expression per region: the high address bits name it."""
        selects = {}
        for name, (base, size) in self.host_map.regions.items():
            low            = log2_exact(size)
            selects[name]  = self.host_addr[self.host_map.addr_bits - 1, low] == (base >> low)
        return selects

    def _drive_status(self) -> None:
        """REG_STATUS bit by bit: each a part-select drive, the undriven bits read 0."""
        bits = ((STATUS_STARTED,            self.data_mem.read_ready),
                (STATUS_FINISHED,           self.finished),
                (STATUS_EXIT_SEEN,          self.exit_seen),
                (STATUS_CYCLE_LIMIT_HIT,    self.cycle_limit_hit),
                (STATUS_CONSOLE_OVERFLOW,   self.console_overflow),
                (STATUS_HOST_WRITE_REFUSED, self.instr_mem.host_write_refused | self.data_mem.host_write_refused))
        for mask, value in bits:
            bit = log2_exact(mask)
            self.status[bit, bit] *= value
