# AluExecUnit — the integer ALU's semantics: one stage, one result, always
# to the destination slot. A natural-Kathryn exec_stage body
# (isa/exec_unit.py) over the station record's fields.
#
# The slots are read by CORE, never by field: src 1 is the value (rs, or rt
# for a shift / seb / seh), src 2 the second operand (rt, an immediate, a
# shift count), src 3 what movz/movn keep and where ins finds its positions.
#
# Sign handling is structural, never a signed type: flip the sign bit for a
# signed compare, XOR-subtract to sign-fill a shift.
# LIMIT: add / addi / sub do not trap on overflow (no trap policy).

from __future__ import annotations

from kathryn import mux, val, wire

from ..exec_unit import ExecUnitBase
from ..exec_unit_util import drive_by_uop, sext_byte, sext_half
from . import uop as U
from .operand import AOPR_DEST_1, AOPR_SRC_1, AOPR_SRC_2, AOPR_SRC_3
from .reg import SIGN, X_LEN


class AluExecUnit(ExecUnitBase):
    """The integer ALU, every result to rd or rt through one slot."""

    def exec_stage(self, stage_idx, src, api):
        a  = api.get_src(src, AOPR_SRC_1)
        b  = api.get_src(src, AOPR_SRC_2)
        c  = api.get_src(src, AOPR_SRC_3)
        sh = b & (X_LEN - 1)                        # a shift count is the low five bits
        # Sign-fill: msk is the sign bit shifted to where it lands, and
        # (v ^ msk) - msk extends it.
        msk = (a & SIGN) >> sh
        # a rotate right by sh is a shift right OR-ed with a shift left by 32 - sh
        rot = (a >> sh) | (a << ((val(X_LEN, X_LEN) - sh) & (X_LEN - 1)))

        # ext/ins read their positions off the packed immediate (imm.py):
        # bits 4..0 the low position, bits 12..8 size-1 (ext) or msb (ins).
        # `2 << msbd` - 1 is the size mask, and a 32-wide field wraps to all ones.
        ext_pos, ext_msbd = b[4, 0], b[12, 8]
        ins_lsb, ins_msb  = c[4, 0], c[12, 8]
        ext_mask = (val(X_LEN, 2) << ext_msbd) - 1
        ins_mask = ((val(X_LEN, 2) << ins_msb) - 1) & ~((val(X_LEN, 1) << ins_lsb) - 1)

        # count leading zeros / ones: the highest set bit is muxed in last, so it wins
        clz = val(X_LEN, X_LEN)
        clo = val(X_LEN, X_LEN)
        for i in range(X_LEN):
            clz = mux(a[i],      val(X_LEN, X_LEN - 1 - i), clz)
            clo = mux(a[i] == 0, val(X_LEN, X_LEN - 1 - i), clo)

        result = wire(X_LEN, "alu_result")
        drive_by_uop(result, src, (
            ((U.UOP_ADD, U.UOP_ADDU, U.UOP_ADDI, U.UOP_ADDIU), a + b),
            ((U.UOP_SUB, U.UOP_SUBU),                          a - b),
            ((U.UOP_AND, U.UOP_ANDI),                          a & b),
            ((U.UOP_OR,  U.UOP_ORI),                           a | b),
            ((U.UOP_XOR, U.UOP_XORI),                          a ^ b),
            (U.UOP_NOR,                                        ~(a | b)),
            # Signed order is unsigned order with the sign bit flipped.
            ((U.UOP_SLT,  U.UOP_SLTI),                         (a ^ SIGN) < (b ^ SIGN)),
            ((U.UOP_SLTU, U.UOP_SLTIU),                        a < b),
            (U.UOP_LUI,                                        b),           # imm16 << 16, placed by imm.py
            ((U.UOP_SLL,  U.UOP_SLLV),                         a << sh),
            ((U.UOP_SRL,  U.UOP_SRLV),                         a >> sh),
            ((U.UOP_SRA,  U.UOP_SRAV),                         ((a >> sh) ^ msk) - msk),
            ((U.UOP_ROTR, U.UOP_ROTRV),                        rot),
            (U.UOP_MOVZ,                                       mux(b == 0, a, c)),
            (U.UOP_MOVN,                                       mux(b != 0, a, c)),
            (U.UOP_CLZ,                                        clz),
            (U.UOP_CLO,                                        clo),
            (U.UOP_SEB,                                        sext_byte(a & 0xff)),
            (U.UOP_SEH,                                        sext_half(a & 0xffff)),
            (U.UOP_EXT,                                        (a >> ext_pos) & ext_mask),
            (U.UOP_INS,                                        (b & ~ins_mask) | ((a << ins_lsb) & ins_mask)),
        ))

        api.wb_reg(AOPR_DEST_1, result)
        api.declare_fin(src)
        return None                                 # last stage: no next
