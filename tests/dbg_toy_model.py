# The toy pipeline the debug-probe tests build: three PipCons and a 4-row log.
#
#   con_a  pip(auto_req) ── zync ──▶ con_b  pip ── zync(go) ──▶ con_o  no_pip_master
#                                    hold = ~go        └─ log[wr_ptr] <= a, wr_ptr++
#
# `go` is low four cycles out of eight. While it is low con_b is HELD, so A's
# zync WAITS on it and stage A reads STALL; B's own hop to con_o is cond-gated,
# so the sink's leaf reads QUIET. DbgToyBase has no @dbg of its own: it is the
# "without debug" control the byte-identical-Verilog test builds.
# NOT here: a stall through a parked zync alone — a pip's entrance re-arms off
# its zync's state register, so a parked zync does not hold the stage upstream
# (docs/open_items.md, "A parked zync does not back-pressure").

from __future__ import annotations

from kathryn import HwComponentType, Karray, Module, PipCon, dbg, flow, init, kaf, pip, reg, val, wire, zync

from carolyne.debug.sim import KarrayProbe, PipStatusProbe

# con_b's leaves in creation order: A's zync first, then B's own pip leaf.
CON_B_ZYNC_LEAF = 0
CON_O_ZYNC_LEAF = 0
LOG_ROWS        = 4


class LogEntry(Karray):
    valid = kaf(1)
    data  = kaf(8)


class DbgToyBase(Module):
    @init
    def com_declare(self):
        self.con_a = PipCon()
        self.con_b = PipCon()
        self.con_o = PipCon()
        self.con_o.no_pip_master()

        self.a      = reg(8, "a")
        self.b      = reg(8, "b")
        self.go     = reg(1, "go")
        self.tick   = reg(3, "tick")
        self.wr_ptr = reg(2, "wr_ptr")
        self.hold_b = wire(1, "hold_b")
        self.log    = LogEntry(HwComponentType.REG, (LOG_ROWS,), "log")
        self.one8   = val(8, 1, "one8")
        self.one3   = val(3, 1, "one3")
        self.one2   = val(2, 1, "one2")

    @flow
    def my_flow(self):
        self.a     .reset(0)
        self.b     .reset(0)
        self.go    .reset(1)
        self.tick  .reset(0)
        self.wr_ptr.reset(0)
        self.log   .reset(valid=0)

        self.tick   |= self.tick + self.one3
        self.go     |= self.tick[2]
        self.hold_b *= ~self.go
        self.con_b.set_hold(self.hold_b)

        with pip(self.con_a, auto_req=True):
            with zync(self.con_b):
                self.a |= self.a + self.one8

        with pip(self.con_b):
            with zync((self.con_o, self.go)):
                self.b               |= self.a
                self.log[self.wr_ptr] |= {"valid": 1, "data": self.a}
                self.wr_ptr          |= self.wr_ptr + self.one2


class DbgToy(DbgToyBase):
    @dbg
    def dbg_declare(self):
        self.pipe_a    = PipStatusProbe(self.con_a)
        self.pipe_b    = PipStatusProbe(self.con_b)
        self.pipe_o    = PipStatusProbe(self.con_o)
        self.log_probe = KarrayProbe(self.log, head=self.wr_ptr)
