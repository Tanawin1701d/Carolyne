# A ZYNC BODY READS WHAT ITS OWN CYCLE DRIVES. The LS address stage computes
# the effective address, the forwarded word and the merged store data, then
# hands them to the next stage and the store buffer inside its handshake
# block. Kathryn gates a wire driven in a pip body on the ENTRY node's state
# and the block's writes on the zync's own state: the two agree in the cycle
# the stage is entered and disagree once the block has parked — the entry
# state is gone, the wires read zero, and the grant pushes `@0 = 0`. Found on
# riscv_temp: the store after a squash cycle printed nothing; hanoi and fib
# looped forever on stack reads of zero. Pinned by structure, and on the
# emitted guard of `ls_eff_addr` in the whole machine.

from __future__ import annotations

import ast
import inspect
import re

from kathryn import build_model, emit_verilog, reset

from carolyne.isa.riscv.exec_unit_ls import LSExecUnit
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config


def test_every_drive_of_the_address_stage_is_inside_the_handshake():
    source = inspect.getsource(LSExecUnit._address_stage)
    tree   = ast.parse(source.lstrip())
    withs  = [n for n in ast.walk(tree) if isinstance(n, ast.With)
              and "zync_with_next_stage" in ast.dump(n)]
    assert len(withs) == 1
    inside = {id(n) for n in ast.walk(withs[0])}
    drives = [n for n in ast.walk(tree) if isinstance(n, ast.AugAssign)
              and isinstance(n.op, (ast.BitOr, ast.Mult))]
    assert drives, "the stage drives something"
    outside = [ast.unparse(n) for n in drives if id(n) not in inside]
    assert not outside, f"driven before the handshake: {outside}"


def _guard_leaves(verilog: str, wire_prefix: str) -> set[str]:
    """The state registers the named wire's guarded drive depends on."""
    assigns = dict(re.findall(r"^assign (\S+) = (.+);$", verilog, re.M))
    guard   = re.search(
        r"if \((EXPR_node_logic_expr_\d+)\) begin\s*\n\s*(?:if \([^\n]*\) begin\s*\n\s*)*"
        + wire_prefix + r"_\d+\[", verilog)
    assert guard, f"no guarded drive of {wire_prefix}"
    leaves, todo, seen = set(), [guard.group(1)], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        rhs = assigns.get(name)
        if rhs is None:
            if name.startswith("SR_ST_"):
                leaves.add(re.sub(r"_\d+.*$", "", name))
            continue
        todo += re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rhs)
    return leaves


def test_the_address_wire_is_gated_on_the_zync_state_not_the_entry_node(tmp_path):
    reset()
    build_model(build_machine(gen_o3_rv32im_config()))
    emit_verilog(str(tmp_path), "ls_park")
    verilog = "\n".join(p.read_text() for p in tmp_path.glob("MODULE_ExecUnitO3*.v"))
    leaves  = _guard_leaves(verilog, "WIRE_ls_eff_addr")
    assert "SR_ST_zync_state" in leaves, leaves
    assert "SR_ST_par_state" not in leaves, leaves
