# Smallest end-to-end Kathryn flow, CPU-flavored: a 4-entry x 8-bit register
# file with one write port, one read port, and an accumulator that sums every
# value ever written. Demonstrates the pieces Carolyne's uarch will lean on:
#
#   - Module subclass with @init (declare hardware) / @flow (behavior)
#   - reg / wire, IO marking, reset()
#   - seq (clocked |= / comb *=) and sif conditional blocks
#   - Karray with dynamic indexing: rf[addr] writes guard per element,
#     rf[addr] reads materialise a mux tree
#   - gen_flow -> build_flow -> emit_verilog
#
# Run:  .venv/bin/python examples/regfile_demo.py
# Out:  generated/regfile_demo.v  (plus one .v per submodule, none here)

import os

from kathryn import (
    reset, set_top, Module, init, flow,
    reg, wire, seq, sif,
    Karray, kaf, HwComponentType,
    gen_flow, build_flow, emit_verilog,
)


class RfEntry(Karray):
    # One field per element; fields become their own per-element HCPs
    # (rf_E0_data ... rf_E3_data in the emitted Verilog).
    data = kaf(8)


class regfile_demo(Module):
    @init
    def decl(self):
        # IO — a wire marked input/output becomes a port of this module.
        self.wr_en   = wire(1).mark_input("wr_en")
        self.wr_addr = wire(2).mark_input("wr_addr")
        self.wr_data = wire(8).mark_input("wr_data")
        self.rd_addr = wire(2).mark_input("rd_addr")
        self.rd_data = wire(8).mark_output("rd_data")

        # State: reg-backed Karray (the register file) + a plain accumulator.
        self.rf  = RfEntry(HwComponentType.REG, (4,), "rf")
        self.acc = reg(8, "acc")
        self.rd_q = reg(8, "rd_q")     # registered read result

    @flow
    def f(self):
        self.acc.reset(0)

        # Write port: only when wr_en. rf[wr_addr] is a dynamic (binary-address)
        # write — each element updates under a generated (wr_addr == k) guard,
        # the others hold.
        with sif(self.wr_en == 1):
            with seq():
                self.rf[self.wr_addr].data |= self.wr_data
                self.acc |= self.acc + self.wr_data

        # Read port: rf[rd_addr] materialises a mux over all elements; register
        # it, then drive the output wire combinationally from the register.
        with seq():
            self.rd_q    |= self.rf[self.rd_addr].data
            self.rd_data *= self.rd_q


def main() -> None:
    out_dir = os.path.join(os.path.dirname(__file__), "..", "generated")
    os.makedirs(out_dir, exist_ok=True)

    reset()                        # fresh singleton arena
    set_top(regfile_demo())        # instantiate (runs @init) and make it top
    gen_flow()                     # run the deferred @flow methods
    build_flow()                   # host build pass: schematics, clk/reset wiring
    emit_verilog(out_dir, "regfile_demo")   # consumes the arena

    path = os.path.join(out_dir, "regfile_demo.v")
    print(f"wrote {os.path.abspath(path)}\n")
    print(open(path).read())


if __name__ == "__main__":
    main()
