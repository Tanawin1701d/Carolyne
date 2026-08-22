# The execution units this machine provides for RV32I's op vocabulary
# (uop_contract.md §1.2), and — for the ALU — what those ops COMPUTE.
#
# The unit split is a MACHINE choice, not an ISA one: one unit per §1.2 row is
# the plain default, and this file is where an issue-port / unit-count config
# knob will sit. MULDIV is absent — the M extension is not RV32I.
#
# `exec_units()` is a FUNCTION where the ops are constants, since the unit set
# is the configuration knob: two machines may want different splits of one
# vocabulary. Each unit declares its PORT SHAPE (the operand slots it reads and
# writes), which IsaBase then holds every µop to — so a name the ALU body reads
# is a name the record is guaranteed to have.
#
# AluUnit is the ISA's first SEMANTICS, written against the ExecContext
# (isa/exec_context.py). mem/control/system stay plain ExecUnit: their bodies
# need the mem/redirect/trap facilities, which have no contract yet, so `needs`
# declares the request meanwhile.

from __future__ import annotations

from typing import Tuple

from ..exec_context import ExecContext
from ..exec_unit import ExecUnit, ExecUnitBase
from ..op import Op
from . import op as O
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3
from .reg import X_LEN


class AluUnit(ExecUnitBase):
    """The integer ALU's semantics: ctx reads/writes plus Python operators, no
    Kathryn. The body always EXECUTES — it is building hardware — so every
    result is computed and `ctx.when` guards only the write; nothing here
    branches in Python on a runtime value. The op guards are mutually
    exclusive, which is why the twelve writes to one destination need no
    priority between them."""

    def build_exec(self, ctx: ExecContext) -> None:
        a, b = ctx.src("src_1"), ctx.src("src_2")
        sh   = b & (X_LEN - 1)               # shift count is src2[4:0]
        sign = 1 << (X_LEN - 1)

        def out(op: Op, value) -> None:
            with ctx.when(ctx.op_is(op)):
                ctx.write("dest_1", value)

        out(O.ADD,  a + b)
        out(O.SUB,  a - b)                   # the write truncates; wraparound falls out
        out(O.AND,  a & b)
        out(O.OR,   a | b)
        out(O.XOR,  a ^ b)
        out(O.SLL,  a << sh)
        out(O.SRL,  a >> sh)
        # Sign-fill without a signed type: msk is the sign bit shifted to where
        # it lands, and (v ^ msk) - msk extends it — the same result under
        # 32-bit wraparound and under a truncating write on plain ints.
        msk = (a & sign) >> sh
        out(O.SRA,  ((a >> sh) ^ msk) - msk)
        # Signed order is unsigned order with the sign bit flipped.
        out(O.SLT,  (a ^ sign) < (b ^ sign))
        out(O.SLTU, a < b)
        out(O.MOV_IMM, b)                    # lui: the assembled U-imm rides in src_2
        out(O.AUIPC,   ctx.pc() + b)         # pc of THIS µop, read off the record


def exec_units() -> Tuple[ExecUnit, ...]:
    """The units this machine provides for RV32I's vocabulary.

    One unit per §1.2 row is the plain default; a wider machine (two ALUs, a
    second load/store port) is expressed here and nowhere else.
    """
    return (AluUnit("alu",      {O.ADD, O.SUB, O.AND, O.OR, O.XOR,
                                 O.SLL, O.SRL, O.SRA, O.SLT, O.SLTU,
                                 O.MOV_IMM, O.AUIPC},
                    src_operands=(AOPR_SRC_1, AOPR_SRC_2),
                    dest_operands=(AOPR_DEST_1,)),
            ExecUnit("mem",     {*O.LOADS, *O.STORES},
                     src_operands=(AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
                     dest_operands=(AOPR_DEST_1,),
                     needs=("mem",)),
            ExecUnit("control", {*O.BRANCHES, O.JMP, O.JMP_INDIRECT},
                     src_operands=(AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
                     dest_operands=(AOPR_DEST_1,),
                     needs=("redirect",)),
            # ecall/ebreak/fence name no operand at all.
            ExecUnit("system",  {O.FENCE, O.TRAP}))
