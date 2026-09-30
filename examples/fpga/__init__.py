# The FPGA flow: a BUILT machine to a bitstream, the bitstream to a board, and
# the board's answer compared with the simulator's. Nothing here is machine
# model — the O3 side (examples/o3/fpga/system.py) builds the machine with
# its HostBridge and hands this package the result.
#
#   bridge/      the HostBridge: the window a host sees, the driver protocol, the hardware
#   backend/     synthesis backends behind one registry (vivado/ today)
#   board/       reaching the board over ssh and running the driver there
#   system.py    the contract a machine family builds an FpgaMachine / FpgaProgram to
#   options.py   what the FLOW varies (backend, board, clock)
#   runner.py    bitstream build (cached), the board run, the board-in-simulation run
#   result.py    the driver's raw outcome rendered into the sim's RunResult
#   compare.py   sim RunResult against board RunResult
#   sweep.py     every program on one bitstream, with the sim beside it
#   cli.py       the command line, and the one table that names machine families
#
# Usage:
#     python -m examples.fpga build  --target rv32im
#     python -m examples.fpga run    examples/compile_tool/programs/hello.c
#     python -m examples.fpga simrun examples/compile_tool/programs/hello.c
#     python -m examples.fpga sweep  --target rv32im --compare-sim

from __future__ import annotations
