# BrExecUnit — the pc-augmenting µops (the branches and the jumps): resolve
# the branch, compute the real next pc, and say whether the prediction held.
# A natural-Kathryn exec_stage body (isa/exec_unit.py).
#
# The station kind is RSV_BRANCH, so the record carries `pc` AND `npc`. On
# MIPS `npc` (pc + 4) is the DELAY SLOT's address and the base of every
# target: a branch adds its offset to it, j/jal take its top four bits, and
# the link value is pc + 8, the instruction after the slot.
#
# The engine does not read the "delay_slot" feature yet, so the build holds
# every slot to a nop (compile_tool verify.py). Under that rule the real next
# pc of a not-taken branch IS npc, which is what the record predicts, and a
# taken one squashes the nop and continues at the target — so the compare is
# the same one RV32I makes, actual npc against predicted.
#
# The link writeback is GATED in a zif on the four link µops: a branch that
# writes nothing booked no physical register, and an unguarded write would
# land on a garbage pr_idx.

from __future__ import annotations

from kathryn import mux, val, wire, zif
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from ..exec_unit_util import drive_by_uop, uop_hit
from . import uop as U
from .field_match import ILEN_BYTES
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3
from .reg import X_LEN

REGION_MASK = 0xF0000000          # the top four bits a j/jal target keeps from npc


class BrExecUnit(ExecUnitBase):
    """Branch resolution: taken, target, and the npc compare."""

    def exec_stage(self, stage_idx, src, api):
        a   = to_ref(api.get_src(src, AOPR_SRC_1))   # rs
        b   = api.get_src(src, AOPR_SRC_2)           # rt, for beq/bne
        imm = api.get_src(src, AOPR_SRC_3)           # the placed offset or jump index
        pc  = to_ref(src[0].pc)
        npc = to_ref(src[0].npc)                     # pc + 4: the delay slot
        a_neg  = a[X_LEN - 1]
        a_zero = a == 0

        taken = wire(1, "br_taken")
        drive_by_uop(taken, src, (
            (U.UOP_BEQ,                  a == b),
            (U.UOP_BNE,                  a != b),
            (U.UOP_BLEZ,                 a_neg | a_zero),
            (U.UOP_BGTZ,                 (a_neg == 0) & (a != 0)),
            ((U.UOP_BLTZ, U.UOP_BLTZAL), a_neg),
            ((U.UOP_BGEZ, U.UOP_BGEZAL), a_neg == 0),
            (U.JUMPS,                    val(1, 1)),          # jumps always go
        ))

        target = wire(X_LEN, "br_target")
        drive_by_uop(target, src, (
            (U.BRANCHES,             npc + imm),
            ((U.UOP_J,  U.UOP_JAL),  (npc & REGION_MASK) | imm),
            ((U.UOP_JR, U.UOP_JALR), a),
        ))

        # The real next pc, against the predicted one the record carries:
        # a mispredict IS "actual differs from predicted".
        actual_npc = mux(to_ref(taken), to_ref(target), npc)
        mis_pred   = wire(1, "br_mis_pred")
        mis_pred  *= actual_npc != npc
        suc_pred   = wire(1, "br_suc_pred")
        suc_pred  *= actual_npc == npc

        # the return address is the instruction AFTER the delay slot
        link  = wire(X_LEN, "br_link")
        link *= pc + 2 * ILEN_BYTES
        with zif(uop_hit(src, U.LINKS)):
            api.wb_reg(AOPR_DEST_1, link)

        api.declare_mis_pred(mis_pred, actual_npc)
        api.declare_suc_pred(suc_pred)
        api.declare_fin(src)
        return None                                 # last stage: no next
