# The HostBridge — how a host (the PS on the board, or a testbench) loads a
# program into the machine, starts it, and reads the result back.
#
#   bridge_map.py          the window: regions, registers, status bits, port names   (stdlib)
#   bridge_driver.py       the protocol over WordPort / ResetLine, and its outcome   (stdlib)
#   bridge_run_spec.py     one run as the driver reads it, one JSON per run dir      (stdlib)
#   bridge_port_cocotb.py  the port and reset line over a simulated bridge           (cocotb)
#   bridge_port_pynq.py    the same over PYNQ's MMIO and an AXI GPIO                  (pynq)
#   bridge_hardware.py     HostBridge, the Kathryn module the machine instantiates   (kathryn)
#
# This __init__ imports the stdlib files ONLY: the board gets a copy of this
# directory (examples/fpga/board/deploy.py) and has neither kathryn nor cocotb.

from __future__ import annotations

from .bridge_driver   import (STOP_EXIT, STOP_MAX_CYCLES, STOP_TIMEOUT, BridgeMismatch,
                              HostDriver, HostRunOutcome, HostStatus, ResetLine, WordPort,
                              interleave_banks)
from .bridge_map      import (CONSOLE_TAGS, CONSOLE_WORDS, CTRL_START, DMEM, HOST_ADDR, HOST_BRAM_CELL,
                              HOST_EN, HOST_PORT_NAMES, HOST_RDATA, HOST_WDATA, HOST_WE, IMEM, MAGIC_WORD,
                              MAP_VERSION, REG_CONSOLE_COUNT, REG_CTRL, REG_CYCLE_LIMIT,
                              REG_CYCLES, REG_EXIT_CODE, REG_GEOMETRY, REG_MAGIC, REG_SCRATCH,
                              REG_STATUS, REGION_ORDER, REGS, RESET_GPIO_CELL, STATUS_CONSOLE_OVERFLOW,
                              STATUS_CYCLE_LIMIT_HIT, STATUS_EXIT_SEEN, STATUS_FINISHED,
                              STATUS_HOST_WRITE_REFUSED, STATUS_STARTED, TAG_PUTCHAR, TAG_PUTINT,
                              HostMap)
from .bridge_run_spec import (OUT_DIR_ENV, SPEC_ENV, SPEC_FILE, BridgeRunSpec,
                              read_bridge_run_spec, read_hex_words, write_bridge_run_spec)

__all__ = ["HostMap", "HostDriver", "HostRunOutcome", "HostStatus", "WordPort", "ResetLine",
           "BridgeMismatch", "interleave_banks",
           "BridgeRunSpec", "read_bridge_run_spec", "write_bridge_run_spec", "read_hex_words",
           "SPEC_ENV", "SPEC_FILE", "OUT_DIR_ENV",
           "STOP_EXIT", "STOP_MAX_CYCLES", "STOP_TIMEOUT",
           "REGS", "CONSOLE_WORDS", "CONSOLE_TAGS", "IMEM", "DMEM", "REGION_ORDER",
           "REG_MAGIC", "REG_GEOMETRY", "REG_CTRL", "REG_STATUS", "REG_CYCLES", "REG_EXIT_CODE",
           "REG_CONSOLE_COUNT", "REG_CYCLE_LIMIT", "REG_SCRATCH",
           "CTRL_START", "STATUS_STARTED", "STATUS_FINISHED", "STATUS_EXIT_SEEN",
           "STATUS_CYCLE_LIMIT_HIT", "STATUS_CONSOLE_OVERFLOW", "STATUS_HOST_WRITE_REFUSED",
           "TAG_PUTCHAR", "TAG_PUTINT", "MAGIC_WORD", "MAP_VERSION",
           "HOST_EN", "HOST_WE", "HOST_ADDR", "HOST_WDATA", "HOST_RDATA", "HOST_PORT_NAMES",
           "HOST_BRAM_CELL", "RESET_GPIO_CELL"]
