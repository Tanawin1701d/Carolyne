# The execution units this machine provides for RV32I's µop vocabulary
# (uop_contract.md §1.2), and — for the ALU — what those µops COMPUTE.
#
# The unit split is a MACHINE choice, not an ISA one: one unit per §1.2 row is
# the plain default, and this file is where an issue-port / unit-count config
# knob will sit. MULDIV is absent — the M extension is not RV32I.
#
# `exec_units()` is a FUNCTION where the µops are constants, since the unit set
# is the configuration knob: two machines may want different splits of one
# vocabulary. A unit lists the TEMPLATE INSTANCES uop.py declares — IsaBase
# matches them by identity — so add/addi are two entries, not one.
#
# Each unit declares its PORT SHAPE (the operand slots it reads and writes),
# which IsaBase then holds every µop to — so a name the ALU body reads is a
# name the record is guaranteed to have.
#
# AluUnit is the ISA's first SEMANTICS, written against the generator's
# execution context. mem/control/system stay plain ExecUnit: their bodies
# need the mem/redirect/trap facilities, which have no contract yet, so `needs`
# declares the request meanwhile.

from __future__ import annotations

from typing import Tuple

from ..exec_unit import ExecUnit, ExecUnitBase
from ..uop import Uop
from . import uop as U
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3
from .reg import X_LEN


class AluUnit(ExecUnitBase):
    """The integer ALU's semantics: ctx reads/writes plus Python operators, no
    Kathryn. The body always EXECUTES — it is building hardware — so every
    result is computed and `ctx.when` guards only the write; nothing here
    branches in Python on a runtime value. The µop guards are mutually
    exclusive, which is why the writes to one destination need no priority
    between them.

    A result is written once per µop that produces it, so the register and
    immediate forms of one operation are listed TOGETHER: they compute the same
    thing off src_2, which is rs2 in one and the immediate in the other."""

    def build_exec(self, ctx) -> None:
        a, b = ctx.src("src_1"), ctx.src("src_2")
        sh   = b & (X_LEN - 1)               # shift count is src2[4:0]
        sign = 1 << (X_LEN - 1)

        def out(uops, value) -> None:
            """Write `value` to rd for any of these µops — one guard, OR-ed
            over the group, since they are the same operation encoded twice."""
            hit = None
            for uop in (uops,) if isinstance(uops, Uop) else uops:
                is_it = ctx.uop_is(uop)
                hit   = is_it if hit is None else hit | is_it
            with ctx.when(hit):
                ctx.write("dest_1", value)

        out((U.UOP_ADD,  U.UOP_ADDI),  a + b)
        out(U.UOP_SUB,                 a - b)   # the write truncates; wraparound falls out
        out((U.UOP_AND,  U.UOP_ANDI),  a & b)
        out((U.UOP_OR,   U.UOP_ORI),   a | b)
        out((U.UOP_XOR,  U.UOP_XORI),  a ^ b)
        out((U.UOP_SLL,  U.UOP_SLLI),  a << sh)
        out((U.UOP_SRL,  U.UOP_SRLI),  a >> sh)
        # Sign-fill without a signed type: msk is the sign bit shifted to where
        # it lands, and (v ^ msk) - msk extends it — the same result under
        # 32-bit wraparound and under a truncating write on plain ints.
        msk = (a & sign) >> sh
        out((U.UOP_SRA,  U.UOP_SRAI),  ((a >> sh) ^ msk) - msk)
        # Signed order is unsigned order with the sign bit flipped.
        out((U.UOP_SLT,  U.UOP_SLTI),  (a ^ sign) < (b ^ sign))
        out((U.UOP_SLTU, U.UOP_SLTIU), a < b)
        out(U.UOP_LUI,   b)                  # the assembled U-imm rides in src_2
        out(U.UOP_AUIPC, ctx.pc() + b)       # pc of THIS µop, read off the record


def exec_units() -> Tuple[ExecUnit, ...]:
    """The units this machine provides for RV32I's vocabulary.

    One unit per §1.2 row is the plain default; a wider machine (two ALUs, a
    second load/store port) is expressed here and nowhere else.
    """
    return (AluUnit("alu",      (U.UOP_ADD,  U.UOP_ADDI,  U.UOP_SUB,
                                 U.UOP_AND,  U.UOP_ANDI,
                                 U.UOP_OR,   U.UOP_ORI,
                                 U.UOP_XOR,  U.UOP_XORI,
                                 U.UOP_SLL,  U.UOP_SLLI,
                                 U.UOP_SRL,  U.UOP_SRLI,
                                 U.UOP_SRA,  U.UOP_SRAI,
                                 U.UOP_SLT,  U.UOP_SLTI,
                                 U.UOP_SLTU, U.UOP_SLTIU,
                                 U.UOP_LUI,  U.UOP_AUIPC),
                    src_operands=(AOPR_SRC_1, AOPR_SRC_2),
                    dest_operands=(AOPR_DEST_1,)),
            ExecUnit("mem",     (*U.LOADS, *U.STORES),
                     src_operands=(AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
                     dest_operands=(AOPR_DEST_1,),
                     needs=("mem",)),
            ExecUnit("control", (*U.BRANCHES, U.UOP_JAL, U.UOP_JALR),
                     src_operands=(AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
                     dest_operands=(AOPR_DEST_1,),
                     needs=("redirect",)),
            # ecall/ebreak/fence name no operand at all.
            ExecUnit("system",  (U.UOP_FENCE, U.UOP_ECALL, U.UOP_EBREAK)))
