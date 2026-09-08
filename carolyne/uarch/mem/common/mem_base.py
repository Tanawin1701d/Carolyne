# MEMORY BASE — what every memory has and nothing more: the address shape its
# ports are held to, the ports themselves, and the two builders a subclass
# must supply.
#
# NO STORAGE and NO LOGIC. This class declares no hardware at all; a subclass
# declares its arbiters and its storage in its own @init.
#
# Port creation runs one way: a requestor calls add_read_port / add_write_port,
# the base forwards to the subclass's gen_*, then holds the result to the pivot
# address shape and records it. A subclass overrides gen_*, never add_*.
#
# A port is built in the MEMORY's module, wherever it is asked for: add_* opens
# own_scope() around gen_*, so a requestor calling from its own scope does not
# end up declaring the memory's wires inside itself. Kathryn creates hardware in
# whatever module scope is open, so without this the port would land in the
# caller.

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, List

from kathryn import Module
from kathryn import _session

from carolyne.uarch.mem.common.addr_meta import AddrMeta
from carolyne.uarch.mem.common.mem_port  import MemPortBase, MemPortRead, MemPortWrite


class MemBase(Module):
    """The port surface of a memory: one address shape, two port lists."""

    def __init__(self, addr_meta: AddrMeta):
        # Plain-Python configuration BEFORE super().__init__(): that call runs
        # the @init methods, and a subclass's may already read these.
        if not isinstance(addr_meta, AddrMeta):
            raise ValueError(
                f"MemBase: addr_meta must be an AddrMeta, got {type(addr_meta).__name__}")
        self.addr_meta   : AddrMeta          = addr_meta    # every port matches it
        self.read_ports  : List[MemPortRead]  = []
        self.write_ports : List[MemPortWrite] = []
        super().__init__()

    # --- what a subclass supplies -------------------------------------------

    def gen_read_port(self, *args, **kwargs) -> MemPortRead:
        """Build one read port. A subclass states its own arguments.

        - the memory declares the port's PipCon and picks its PortTiming
        - runs inside the memory's own module scope, so it may declare hardware
        - build only: add_read_port() is what checks and records the result
        """
        raise NotImplementedError(f"{type(self).__name__}: gen_read_port")

    def gen_write_port(self, *args, **kwargs) -> MemPortWrite:
        """Build one write port. A subclass states its own arguments.

        - same split as gen_read_port, and a write must carry its data signal
        - build only: add_write_port() is what checks and records the result
        """
        raise NotImplementedError(f"{type(self).__name__}: gen_write_port")

    # --- what the base does with it -----------------------------------------

    @contextmanager
    def own_scope(self) -> Iterator[None]:
        """Open this memory's module scope, so hardware built inside lands here.

        - one WHOLE flow procedure, the track / finalize / untrack order gen_flow
          uses: a conditional block is a chain master and stays LazyClosed until
          the procedure is finalized, so without that call its hardware attaches
          to nothing and is dropped in silence
        - the flow-block stack is global, so this may not be opened inside a
          caller's own flow block — finalize would then meet the caller's
          unfinished block
        """
        _session.arena().track_module_at_flow_init(self.ident)
        try:
            yield
            _session.arena().finalize_flow_procedure()
        finally:
            _session.arena().untrack_module_at_flow_init(self.ident)

    def add_read_port(self, *args, **kwargs) -> MemPortRead:
        """Build a read port through the subclass, hold it, record it."""
        with self.own_scope():
            port = self.gen_read_port(*args, **kwargs)
        return self._hold_port(port, MemPortRead, self.read_ports)

    def add_write_port(self, *args, **kwargs) -> MemPortWrite:
        """Build a write port through the subclass, hold it, record it."""
        with self.own_scope():
            port = self.gen_write_port(*args, **kwargs)
        return self._hold_port(port, MemPortWrite, self.write_ports)

    def _hold_port(self, port: MemPortBase, kind: type, ports: List) -> MemPortBase:
        # One memory, one address shape: a port naming another one would read
        # a different number of bits than the memory stores.
        where = type(self).__name__
        if not isinstance(port, kind):
            raise ValueError(
                f"{where}: a {kind.__name__} builder returned {type(port).__name__}")
        if port.addr_meta != self.addr_meta:
            raise ValueError(
                f"{where}: port address shape {port.addr_meta} is not the "
                f"memory's {self.addr_meta}")
        ports.append(port)
        return port

    # --- reading them back ---------------------------------------------------

    def get_read_port (self, idx: int) -> MemPortRead : return self.read_ports[idx]
    def get_write_port(self, idx: int) -> MemPortWrite: return self.write_ports[idx]
