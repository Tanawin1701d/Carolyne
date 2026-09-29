# The execution units this machine provides for MIPS32's µop vocabulary
# (uop_contract.md §1.2) — the FACTORY only; each unit's semantics is in
# its own module:
#
#   exec_unit_alu.py    AluExecUnit — every integer template that writes rd/rt
#   exec_unit_br.py     BrExecUnit — what AUGMENTS the pc: branches and jumps
#   exec_unit_ls.py     LSExecUnit — loads and stores, over the LSQ api
#   exec_unit_mul.py    MulExecUnit — the accumulator's multiplies and moves, two stages
#   exec_unit_div.py    DivExecUnit — div/divu, a six-stage restoring divider
#   ../exec_unit_util.py  the body helpers every ISA shares
#
# The unit split is a MACHINE choice, not an ISA one. The unit NAME STRINGS
# ("alu", "mem", "control", "mul", "div") are the ones the station builders
# look up, the same five the RISC-V package uses; the class carries semantics.
#
# Each unit declares its PORT SHAPE, which IsaBase holds every µop to, so a
# field name a body reads is a name the record is guaranteed to have. Only
# mul and div name the accumulator slots, so only their stations carry them.

from __future__ import annotations

from typing import Tuple

from ..exec_unit import ExecUnit
from . import uop as U
from .exec_unit_alu import AluExecUnit
from .exec_unit_br import BrExecUnit
from .exec_unit_ls import LSExecUnit
from .exec_unit_div import STAGE_CNT as DIV_STAGES, DivExecUnit
from .exec_unit_mul import MulExecUnit
from .operand import (AOPR_DEST_1, AOPR_DEST_HI, AOPR_DEST_LO, AOPR_SRC_1, AOPR_SRC_2,
                      AOPR_SRC_3, AOPR_SRC_HI, AOPR_SRC_LO)


def exec_units() -> Tuple[ExecUnit, ...]:
    """The units this machine provides for MIPS32's vocabulary.

    One unit per kind is the plain default; a wider machine (two ALUs) is
    expressed in the machine config, not here.
    """
    return (
        AluExecUnit(
            "alu"    , U.ALUS,
            src_operands  = (AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),   # src 3: movz/movn's rd, ins's positions
            dest_operands = (AOPR_DEST_1,),
        ),
        # two stages: address/forward/merge, then extract/writeback
        LSExecUnit(
            "mem"    , (*U.LOADS, *U.STORES),
            src_operands  = (AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
            dest_operands = (AOPR_DEST_1,),
            needs         = ("mem",),
            stage_cnt     = 2,
        ),
        # pc for the link, npc (the delay slot's pc) for every target
        BrExecUnit(
            "control", U.CONTROL,
            src_operands  = (AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3),
            dest_operands = (AOPR_DEST_1,),
            needs         = ("pc", "npc"),
        ),
        # the accumulator's instructions, split so a divide's six stages never
        # hold up a multiply: each unit takes an in-order station of its own
        MulExecUnit(
            "mul"    , U.MULS,
            src_operands  = (AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_HI, AOPR_SRC_LO),
            dest_operands = (AOPR_DEST_1, AOPR_DEST_HI, AOPR_DEST_LO),
            stage_cnt     = 2,
        ),
        DivExecUnit(
            "div"    , U.DIVS,
            src_operands  = (AOPR_SRC_1, AOPR_SRC_2),
            dest_operands = (AOPR_DEST_HI, AOPR_DEST_LO),
            stage_cnt     = DIV_STAGES,
        ),
    )
