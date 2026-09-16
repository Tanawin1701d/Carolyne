# Debug probes (`carolyne.debug.sim`), each in two explicit halves. The MODEL half is a
# kathryn.DebugProbe a Module stores in its `@dbg` body
# (`self.pipe = PipStatusProbe(self.con)`); the SIM half is built from the
# manifest node by the model probe's own `convert` (`m.pipe.convert(k.pipe)`) and
# carries the reading rules. No hardware is declared: the manifest grows, the Verilog does not.

from __future__ import annotations

from .probe_base            import ProbeBase
from .probe_branch_resolve  import BranchResolveProbe, BranchResolveSimProbe
from .probe_karray     import KarrayProbe, KarraySimProbe
from .probe_mem_port   import MemAccess, MemPortProbe, MemPortSimProbe
from .probe_pip_status import (BUSY, FLUSH, GRANTED, HELD, IDLE, PIP_STATUS_SIGNALS, QUIET, RUNNING, STALL, UNKNOWN,
                               WAITING, PipStatusProbe, PipStatusSimProbe)
from .probe_reg_class  import RegClassProbe, RegClassSimProbe
from .probe_sim_util   import child_or_none, read_value

__all__ = ["ProbeBase", "PipStatusProbe", "PipStatusSimProbe",
           "BranchResolveProbe", "BranchResolveSimProbe",
           "KarrayProbe", "KarraySimProbe", "RegClassProbe", "RegClassSimProbe",
           "MemPortProbe", "MemPortSimProbe", "MemAccess",
           "read_value", "child_or_none", "PIP_STATUS_SIGNALS",
           "RUNNING", "IDLE", "HELD", "BUSY", "STALL", "FLUSH", "UNKNOWN",
           "GRANTED", "WAITING", "QUIET"]
