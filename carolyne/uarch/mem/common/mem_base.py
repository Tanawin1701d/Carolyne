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

from __future__ import annotations

from typing import List

from kathryn import Module

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

        - the memory declares the port's PipCon and picks its PortTiming; the
          address sources, and the data signal when there is one, come from
          the requestor
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

    def add_read_port(self, *args, **kwargs) -> MemPortRead:
        """Build a read port through the subclass, hold it, record it."""
        return self._hold_port(self.gen_read_port(*args, **kwargs),
                               MemPortRead, self.read_ports)

    def add_write_port(self, *args, **kwargs) -> MemPortWrite:
        """Build a write port through the subclass, hold it, record it."""
        return self._hold_port(self.gen_write_port(*args, **kwargs),
                               MemPortWrite, self.write_ports)

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
