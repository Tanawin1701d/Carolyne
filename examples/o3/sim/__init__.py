# The O3 side of the sim flow (examples/sim): the machine emitted for the
# simulator, a program laid out for it, the handoff and the cocotb body.
#   system.py       build_o3_sim_machine / build_o3_sim_program
#   run_spec.py     the run spec: the JSON the cocotb body reads for each program
#   cocotb_run.py   the cocotb body every family's sim_cocotb_test.py calls
