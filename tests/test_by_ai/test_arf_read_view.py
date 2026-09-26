# The Arf's READ VIEW: a commit writes the register at the edge, and the
# rename table drops the mapping on the same cycle's commit row, so a reader
# of that cycle is told "not renamed" and asks the Arf — which must answer
# with the value being committed, not the register's previous one. `write`
# publishes into `read_lane` at PRI_COMMIT, above the plain storage copy, the
# Prf's on_wb shape. Pinned on the emitted Verilog of a standalone Arf.

from __future__ import annotations

import inspect
import re

import pytest
from kathryn import *

from carolyne.isa.riscv.reg import build_x_file
from carolyne.uarch.o3.arf import Arf


class ArfTop(Module):
    @init
    def com_declare(self):
        self.arf    = Arf(build_x_file())
        self.w_idx  = wire(5,  "w_idx")
        self.w_data = wire(32, "w_data")
        self.r_idx  = wire(5,  "r_idx")
        self.r_out  = wire(32, "r_out")

    @flow
    def run(self):
        self.arf.write(self.w_idx, self.w_data)
        self.r_out *= self.arf.read(self.r_idx)


def test_read_answers_from_the_view_not_the_register():
    source = inspect.getsource(Arf.read)
    assert "self.read_lane[dyn_idx]" in source
    assert "self.storage[dyn_idx]" not in source


def test_the_publish_is_emitted_after_the_storage_copy(tmp_path):
    """Both drive read_lane[k].data; priority is emission order, so the
    commit's publish must come LAST in the always block to win."""
    reset()
    set_top(ArfTop("arf_top"))
    gen_flow(); build_flow()
    emit_verilog(str(tmp_path), "arf_top")

    verilog = "\n".join(p.read_text() for p in tmp_path.glob("*.v"))
    # every driver of the view's element 3, in emission order
    drivers = re.findall(r"WIRE_arf_read_x_E3_data_\d+\[31:0\] <= (\S+);", verilog)
    assert len(drivers) >= 2, drivers
    copies = [i for i, d in enumerate(drivers) if "REG_arfx_E3_data" in d]
    assert copies, "the plain storage copy drives the view"
    assert copies[-1] < len(drivers) - 1, "the commit publish is emitted after it"
    assert "w_data" in drivers[-1], "and the publish is the committing value"
