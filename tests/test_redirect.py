# THE REDIRECT PATH: a mispredict must say where execution continues, and the
# corrected pc must beat the front end's own advance.
#
# Before 2026-09-15 nothing called Fetch.override_pc, so a squash emptied the
# pipeline and left the pc wherever the wrong path had run to. These are the
# checks that would have caught it.

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from kathryn import build_model, emit_verilog, reset

from carolyne.uarch.o3.priority import PRI_MIS_PRED
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config

UARCH = pathlib.Path(__file__).resolve().parents[1] / "carolyne" / "uarch" / "o3"
ISA   = pathlib.Path(__file__).resolve().parents[1] / "carolyne" / "isa"


def build_debug_machine():
    reset()
    return build_model(build_machine(gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)), debug=True)


# ---- the contract ---------------------------------------------------------------

def test_a_squash_with_no_corrected_pc_is_refused():
    m   = build_debug_machine()
    exu = m.core.issue_lanes[2].execs[0]                 # the control unit's complex
    src = exu.rsv.exec_src[0]
    with pytest.raises(ValueError, match="pc execution continues at"):
        exu.declare_mis_pred(src, 0, dyn_cond=src[0].is_spec, next_pc=None)


def test_a_squash_with_no_condition_is_refused():
    m   = build_debug_machine()
    exu = m.core.issue_lanes[2].execs[0]
    src = exu.rsv.exec_src[0]
    with pytest.raises(ValueError, match="mispredict condition"):
        exu.declare_mis_pred(src, 0, dyn_cond=None, next_pc=src[0].pc)


def test_override_pc_has_a_caller():
    """The bug this file exists for: the redirect was written and never wired."""
    fetch = (UARCH / "fetch.py").read_text()
    assert "self.override_pc(new_pc, PRI_MIS_PRED)" in fetch
    core = (UARCH / "core.py").read_text()
    assert "self.fetch   .on_mis_pred(redirect_pc)" in core


def test_the_branch_body_states_the_pc_execution_continues_at():
    body = (ISA / "riscv" / "exec_unit_br.py").read_text()
    assert "api.declare_mis_pred(mis_pred, actual_npc)" in body


# ---- the hardware ----------------------------------------------------------------

def test_the_pc_is_written_from_a_value_that_arrives_from_outside_fetch(tmp_path):
    """The redirect is computed in the BRANCH complex, so it reaches Fetch as an
    input port: a pc written only from Fetch's own signals is the old bug."""
    build_debug_machine()
    emit_verilog(str(tmp_path), "top")
    text    = next(tmp_path.glob("MODULE_Fetch*.v")).read_text()
    pc_name = re.search(r"\bREG_pc_\d+\b", text).group(0)

    writes = [line.strip() for line in text.splitlines()
              if re.search(rf"^\s*{pc_name}(\[[^\]]*\])?\s*<=", line)]
    assert len(writes) >= 3, f"expected the advance, the redirect and the reset: {writes}"
    from_outside = [line for line in writes if "IO_WIRE_IO_IN" in line]
    assert from_outside, f"no pc write takes a value from outside Fetch: {writes}"


def test_the_redirect_is_emitted_after_the_ordinary_advance(tmp_path):
    """Priority IS emission order, so the redirect must come after the advance
    and before the reset — otherwise the squash cycle's own step wins."""
    build_debug_machine()
    emit_verilog(str(tmp_path), "top")
    text    = next(tmp_path.glob("MODULE_Fetch*.v")).read_text()
    pc_name = re.search(r"\bREG_pc_\d+\b", text).group(0)

    writes = [line.strip() for line in text.splitlines()
              if re.search(rf"^\s*{pc_name}(\[[^\]]*\])?\s*<=", line)]
    redirect = next(idx for idx, line in enumerate(writes) if "IO_WIRE_IO_IN" in line)
    assert redirect > 0, "the redirect is the FIRST pc write, so the advance would beat it"
    assert PRI_MIS_PRED > 0


def test_the_core_hands_fetch_a_pc_and_not_only_a_flush():
    m = build_debug_machine()
    assert m.core.fetch.on_mis_pred.__code__.co_argcount == 2   # self and the pc
