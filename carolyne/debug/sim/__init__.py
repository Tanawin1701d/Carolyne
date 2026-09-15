# Debug probes (`carolyne.debug.sim`), each in two explicit halves. The MODEL half is a
# kathryn.DebugProbe a Module stores in its `@dbg` body
# (`self.pipe = PipStatusProbe(self.con)`); the SIM half is built from the
# manifest node by the model probe's own `convert` (`m.pipe.convert(k.pipe)`) and
# carries the reading rules. No hardware is declared: the manifest grows, the Verilog does not.

from __future__ import annotations

from .probe_base       import ProbeBase
from .probe_karray     import KarrayProbe, KarraySimProbe
from .probe_pip_status import (BUSY, FLUSH, GRANTED, HELD, IDLE, QUIET, RUNNING, STALL, WAITING, PipStatusProbe,
                               PipStatusSimProbe)
from .probe_reg_class  import RegClassProbe, RegClassSimProbe

__all__ = ["ProbeBase", "PipStatusProbe", "PipStatusSimProbe",
           "KarrayProbe", "KarraySimProbe", "RegClassProbe", "RegClassSimProbe",
           "RUNNING", "IDLE", "HELD", "BUSY", "STALL", "FLUSH", "GRANTED", "WAITING", "QUIET"]
