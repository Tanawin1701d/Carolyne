# The O3 example machine, the descriptions it runs, and its side of each flow.
#   core/     the machine: memories, ports and the core, for ANY CPUO3_Config
#   sim/      the O3 side of examples/sim   (emit, images, run spec, cocotb body)
#   fpga/     the O3 side of examples/fpga  (emit with the HostBridge, images, cocotb test)
#   rv32im/   the RV32IM description and config, plus sim.py / fpga.py bindings
#   mips32/   the MIPS32 description and config, the same shape
