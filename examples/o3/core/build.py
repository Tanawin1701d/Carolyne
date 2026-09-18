# The HARDWARE half of the O3 example: the memories, their ports, and the
# core wired to them — for ANY ISA a CPUO3_Config carries. Nothing here names
# one: the RV32IM config is examples/o3/rv32im/config.py, a MIPS config would
# sit beside it and build this same machine.
#
# Everything is declared inside ONE module's @init. Sibling TOP-LEVEL modules
# share no ancestor and emit_verilog panics on them, so the machine — not the
# core — is the top: it owns the two memories and hands the core only PORTS.
#
# The instruction memory is BANK-PER-LANE and the banks are INTERLEAVED: word w
# sits in bank w % fe_lanes at index w / fe_lanes, and fetch drives one index
# for every lane (uarch/o3/fetch.py). The data memory is one bank with two
# ports, a load path and a store path.

from __future__ import annotations

from kathryn import Module, build_model, init, reset

from carolyne.uarch.mem.easy_mem import EasyMem
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.core import CoreO3


class O3Machine(Module):
    """One out-of-order core with its instruction and data memory."""

    def __init__(self, config: CPUO3_Config):
        # Plain-Python configuration BEFORE super().__init__(): that call runs
        # com_declare, which builds everything from it.
        if not isinstance(config, CPUO3_Config):
            raise TypeError(f"O3Machine: config must be a CPUO3_Config, got {type(config).__name__}")
        self.config = config
        super().__init__()

    @init
    def com_declare(self):
        # The memories, sized by the config: it states the index width, and
        # derives the bank count and the bus from the ISA and the lanes.
        self.instr_mem = EasyMem(*self.config.instr_mem_spec())
        self.data_mem  = EasyMem(*self.config.data_mem_spec())

        # ONE PORT PER LANE. A port names its bank as part of the address, so
        # the memory routes the access and fetch states only a byte address.
        instr_ports = [self.instr_mem.add_read_port(f"lane{lane}")
                       for lane in range(self.config.fe_lanes)]
        # The data memory's two paths: the LS unit loads, the store buffer stores.
        data_read  = self.data_mem.add_read_port ("load")
        data_write = self.data_mem.add_write_port("store")

        self.core = CoreO3(self.config, instr_ports, data_read, data_write)


def build_machine(config: CPUO3_Config) -> O3Machine:
    """The machine, ready for set_top(). Call inside a fresh reset()."""
    return O3Machine(config)


def build_debug_model(config: CPUO3_Config) -> O3Machine:
    """The machine with its debug probes, in a fresh session — ONE recipe, two processes.

    - the process that EMITS and the simulator process that reads probes must
      build the same model: KSim resolves the manifest's names in the compiled
      simulator, so a drift between two copies of this call fails at run time
    - the model cannot travel between them (the simulator is another process),
      so what is shared is this function, not its result
    """
    reset()
    return build_model(build_machine(config), debug=True)
