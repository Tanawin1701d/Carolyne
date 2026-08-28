# The execution units this machine provides for RV32I's µop vocabulary
# (uop_contract.md §1.2) — the FACTORY only; each unit's semantics lives in
# its own module:
#
#   exec_unit_alu.py   AluExecUnit — the integer templates (AUIPC included:
#                      it reads pc but never redirects)
#   exec_unit_br.py    BrExecUnit — what AUGMENTS the pc: branches, jal, jalr
#   exec_unit_ls.py    LSExecUnit — loads/stores, body pending
#   exec_unit_util.py  the shared body helpers (uop_hit / drive_by_uop / SIGN)
#
# The unit split is a MACHINE choice, not an ISA one: one unit per kind is
# the plain default, and this file is where an issue-port / unit-count knob
# will sit. MULDIV is absent — the M extension is not RV32I. The unit NAME
# STRINGS ("alu", "mem", "control", "system") are stable: every lookup in
# the tests and configs keys on them; the class is what carries semantics.
#
# `exec_units()` is a FUNCTION where the µops are constants, since the unit
# set is the configuration knob. A unit lists the TEMPLATE INSTANCES uop.py
# declares — IsaBase matches them by identity — so add/addi are two entries.
# Each unit declares its PORT SHAPE, which IsaBase holds every µop to, so a
# field name a body reads is a name the record is guaranteed to have.

from __future__ import annotations

from typing import Tuple

from ..exec_unit import ExecUnit
from . import uop as U
from .exec_unit_alu import AluExecUnit
from .exec_unit_br import BrExecUnit
from .exec_unit_ls import LSExecUnit
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3


def exec_units() -> Tuple[ExecUnit, ...]:
    """The units this machine provides for RV32I's vocabulary.

    One unit per kind is the plain default; a wider machine (two ALUs, a
    second load/store port) is expressed here and nowhere else.
    """
    return (AluExecUnit("alu", (U.UOP_ADD,  U.UOP_ADDI,  U.UOP_SUB,
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
                        dest_operands=(AOPR_DEST_1,),
                        needs=("pc",)),              # auipc reads it
            LSExecUnit("mem", (*U.LOADS, *U.STORES),
                       src_operands=(AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
                       dest_operands=(AOPR_DEST_1,),
                       needs=("mem",)),
            # pc for the target adder and the link, npc to compare the
            # prediction against — the record fields its body reads.
            BrExecUnit("control", (*U.BRANCHES, U.UOP_JAL, U.UOP_JALR),
                       src_operands=(AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
                       dest_operands=(AOPR_DEST_1,),
                       needs=("pc", "npc")),
            # ecall/ebreak/fence name no operand at all.
            ExecUnit("system", (U.UOP_FENCE, U.UOP_ECALL, U.UOP_EBREAK)))
