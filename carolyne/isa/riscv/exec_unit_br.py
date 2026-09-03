# BrExecUnit — the pc-augmenting µops (the branches, jal, jalr): resolve the
# branch, compute the real next pc, and say whether the prediction held. A
# natural-Kathryn exec_stage body (isa/exec_unit.py).
#
# The station kind is RSV_BRANCH, so the record carries `pc` AND `npc` — the
# predicted next pc this unit compares against.
#
# One stage, so exec_stage returns None. The body DECLARES its resolution:
# api.declare_mis_pred(br_mis_pred) / declare_suc_pred(br_suc_pred) — the
# actual-vs-predicted npc compare — declare_fin, and the link writeback
# GATED in a zif on the jump µops (a branch booked no physical register).
# LIMIT: the core that builds hardware from these calls is pending; the
# gated wb_reg leans on its contract that the call respects the enclosing
# Kathryn scope.

from __future__ import annotations

from kathryn import mux, val, wire, zif
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from . import uop as U
from .exec_unit_util import SIGN, drive_by_uop, uop_hit
from .field_match import ILEN_BYTES
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3
from .reg import X_LEN


class BrExecUnit(ExecUnitBase):
    """Branch resolution: taken, target, and the npc compare."""

    def exec_stage(self, stage_idx, src, api):
        a   = api.get_src(src, AOPR_SRC_1)
        b   = api.get_src(src, AOPR_SRC_2)   # rs2, or jal/jalr's immediate
        imm = api.get_src(src, AOPR_SRC_3)   # the branches' immediate
        pc  = to_ref(src[0].pc)

        taken = wire(1, "br_taken")
        drive_by_uop(taken, src, (
            (U.UOP_BEQ,  a == b),
            (U.UOP_BNE,  a != b),
            (U.UOP_BLT,  (a ^ SIGN) < (b ^ SIGN)),
            (U.UOP_BGE,  ((a ^ SIGN) < (b ^ SIGN)) ^ 1),
            (U.UOP_BLTU, a < b),
            (U.UOP_BGEU, (a < b) ^ 1),
            ((U.UOP_JAL, U.UOP_JALR), val(1, 1)),   # jumps always go
        ))

        target = wire(X_LEN, "br_target")
        drive_by_uop(target, src, (
            (U.BRANCHES, pc + imm),
            (U.UOP_JAL,  pc + b),
            # jalr clears the target's low bit (the spec's & ~1).
            (U.UOP_JALR, (a + b) & ((1 << X_LEN) - 2)),
        ))

        # The real next pc, against the predicted one the record carries:
        # a mispredict IS "actual differs from predicted".
        actual_npc = mux(to_ref(taken), to_ref(target), pc + ILEN_BYTES)
        mis_pred   = wire(1, "br_mis_pred")
        mis_pred  *= actual_npc != to_ref(src[0].npc)
        suc_pred   = wire(1, "br_suc_pred")
        suc_pred  *= actual_npc == to_ref(src[0].npc)

        # jal/jalr's rd: the return path, pc of the NEXT instruction. GATED
        # on the jump µops — a branch booked no physical register, so an
        # unguarded write would land on a garbage pr_idx. Which µops write
        # rd is the ISA's own rule, so the guard sits here, and wb_reg's
        # hardware must respect the enclosing scope (the core's contract).
        link = wire(X_LEN, "br_link")
        link *= pc + ILEN_BYTES
        with zif(uop_hit(src, (U.UOP_JAL, U.UOP_JALR))):
            api.wb_reg(AOPR_DEST_1, link)

        api.declare_mis_pred(mis_pred)
        api.declare_suc_pred(suc_pred)
        api.declare_fin(src)
        return None                                 # last stage: no next
