# AluExecUnit — the integer ALU's semantics: one stage, one result, always
# to rd. A natural-Kathryn exec_stage body (isa/exec_unit.py) over the
# station record's fields.
#
# AUIPC lives HERE, not in BrExecUnit: it reads the pc as an INPUT but never
# redirects, and the unit split is by what AUGMENTS the pc.
#
# One stage, so exec_stage returns None: the result leaves through
# api.wb_reg(AOPR_DEST_1, alu_result). LIMIT: the core that builds the PRF
# write and bypass from that call is pending (declare_fin likewise).

from __future__ import annotations

from kathryn import wire
from kathryn.signal import to_ref

from ..exec_unit import ExecUnitBase
from . import uop as U
from .exec_unit_util import SIGN, drive_by_uop
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2
from .reg import X_LEN


class AluExecUnit(ExecUnitBase):
    """The integer ALU: sign handling is structural, never a signed type —
    flip the sign bit for a signed compare, XOR-subtract to sign-fill a
    shift — the same result under 32-bit wraparound whichever way it is
    read back."""

    def exec_stage(self, stage_idx, src, api):
        a  = api.get_src(src, AOPR_SRC_1)
        b  = api.get_src(src, AOPR_SRC_2)    # rs2 OR the immediate: same slot
        sh = b & (X_LEN - 1)                 # shift count is src2[4:0]
        # Sign-fill: msk is the sign bit shifted to where it lands, and
        # (v ^ msk) - msk extends it.
        msk = (a & SIGN) >> sh

        result = wire(X_LEN, "alu_result")
        drive_by_uop(result, src, (
            ((U.UOP_ADD,  U.UOP_ADDI),  a + b),
            (U.UOP_SUB,                 a - b),     # truncation wraps it
            ((U.UOP_AND,  U.UOP_ANDI),  a & b),
            ((U.UOP_OR,   U.UOP_ORI),   a | b),
            ((U.UOP_XOR,  U.UOP_XORI),  a ^ b),
            ((U.UOP_SLL,  U.UOP_SLLI),  a << sh),
            ((U.UOP_SRL,  U.UOP_SRLI),  a >> sh),
            ((U.UOP_SRA,  U.UOP_SRAI),  ((a >> sh) ^ msk) - msk),
            # Signed order is unsigned order with the sign bit flipped.
            ((U.UOP_SLT,  U.UOP_SLTI),  (a ^ SIGN) < (b ^ SIGN)),
            ((U.UOP_SLTU, U.UOP_SLTIU), a < b),
            (U.UOP_LUI,   b),                       # assembled U-imm in src_2
            (U.UOP_AUIPC, to_ref(src.pc) + b),      # pc of THIS µop
        ))

        api.wb_reg(AOPR_DEST_1, result)
        api.declare_fin(src)
        return None                                 # last stage: no next
