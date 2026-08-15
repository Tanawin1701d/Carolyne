# One Uop template per RV32I instruction — the µop an instruction decodes to,
# transcribed from the RV32I base listing (RISC-V unprivileged spec, ch. 36).
# Every instruction is exactly ONE µop here: RV32I has no AGU (addressing is
# base+imm, computed in the mem unit) and no separate link µop (the jumps
# write rd themselves), so nothing cracks. See the rv32i.py header.
#
# Decisions (2026-08-14):
# - Module CONSTANTS named UOP_<mnemonic>, one per row of the listing, so the
#   table in rv32i.py reads as encodings → named instructions and this file
#   is the one place an instruction is written down.
# - Each template declares its own `matcher_field`: the funct field that picks it
#   out of its opcode group. That belongs with the instruction, not with the
#   sequence wrapping it — "SRAI is the funct7 0100000 one" is a fact about
#   SRAI. rv32i.py is then purely the opcode grouping. LUI/AUIPC/JAL have
#   none: their opcode alone identifies them.
# - Where an instruction needs BOTH funct3 and funct7 (add vs sub, srl vs
#   sra, the shift-immediates), the template names FM.FUNCT3_7 — one rule
#   spanning both fields, built with InstrFieldMatch.union. A single
#   `matcher_field` slot is enough because a rule may cover several fields.
# - (2026-08-15) Every template that names a field also states its
#   `matcher_value`, so the funct values are CODE, not comments, and the table
#   is genuinely discriminable — add vs sub differ by a value on the same
#   field. Written as `FM.val(...)`, one value per segment of the field, in
#   the field's own segment order: beside FM.FUNCT3_7 that is funct3 then
#   funct7, because that is the order FUNCT3_7 was unioned in. Uop's
#   check_matcher_pair holds the two to each other, so a value too wide for
#   its segment or a count that does not match the segments fails here at
#   import, not in a generator.
# - LUI/AUIPC/JAL name NO field and therefore no value: their opcode alone
#   identifies them, and the opcode is the Mop's rule, not the template's.
# - Two mnemonics share one Uop constant only when they are the same
#   operation on the same operands; they never are here, because width, sign
#   and branch condition are distinct Ops (op.py), so the file is 1:1 with
#   the listing.
# - ADDI/SLTI/... reuse the ALU Op of their register form (ADD, SLT, ...):
#   the operation is identical, only the second operand rule differs, which
#   is exactly what the operand tuple says. SLLI/SRLI/SRAI take SHAMT rather
#   than IMM_I — a 5-bit count, not a 12-bit signed value.
# - The immediate rides in `srcs` as an operand (OPR_IMM_*), because that is
#   the only slot this layer has: `Uop.imm` does not exist while the matcher
#   design is in flight. NOTE the tension — contract §2 says an immediate is
#   NOT an operand and rides in its own record field, so the ≤3 src cap it
#   specifies does not budget for one. RV32I still fits (store and branch are
#   the widest, at rs1+rs2+imm = 3), but the contract has to settle which way
#   this goes before the record is generated.
#
# KNOWN GAPS carried from the layer below:
# - A value says WHICH BITS but not where each segment lands in an assembled
#   field, so the funct matchers here are complete but the immediate
#   *extractors* still are not (field_match.py). Discriminating works;
#   building the immediate value does not.
# - auipc, jal and jalr need the instruction's own PC as an input, which no
#   operand can name (reg.py: PC is not a register class). Their `srcs` are
#   the encoding's operands only.
# - The branch/jump redirect is not expressed: the control FU takes it from
#   the op plus the immediate, and no dest names it.

from __future__ import annotations

from ..uop import Uop
from . import field_match as FM
from . import op as O
from .operand import (OPR_IMM_B, OPR_IMM_I, OPR_IMM_J, OPR_IMM_S,
                      OPR_IMM_SHAMT, OPR_IMM_U, OPR_RD, OPR_RS1, OPR_RS2)

_RD    = (OPR_RD,)
_BR    = (OPR_RS1, OPR_RS2, OPR_IMM_B)      # branch: two compares + target
_ADDR  = (OPR_RS1, OPR_IMM_I)               # load:   base + displacement
_STORE = (OPR_RS1, OPR_RS2, OPR_IMM_S)      # store:  base + data + displacement
_IMM   = (OPR_RS1, OPR_IMM_I)               # op-imm: register + 12-bit signed
_SHIFT = (OPR_RS1, OPR_IMM_SHAMT)           # shift-imm: register + 5-bit count
_REG   = (OPR_RS1, OPR_RS2)                 # op:     two registers

# --- U-type, opcode 0110111 / 0010111: rd = imm ------------------------------
# No funct field: the opcode alone identifies these, so no matcher at all.
UOP_LUI   = Uop(O.MOV_IMM, srcs=(OPR_IMM_U,), dests=_RD)
UOP_AUIPC = Uop(O.AUIPC,   srcs=(OPR_IMM_U,), dests=_RD)

# --- jumps, opcode 1101111 / 1100111: rd = pc + ilen, then redirect ----------
UOP_JAL  = Uop(O.JMP,          srcs=(OPR_IMM_J,), dests=_RD)          # opcode alone
UOP_JALR = Uop(O.JMP_INDIRECT, srcs=_ADDR, dests=_RD,
               matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))

# --- B-type, opcode 1100011: redirect when the test holds, no destination ----
UOP_BEQ  = Uop(O.BEQ,  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_BNE  = Uop(O.BNE,  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_BLT  = Uop(O.BLT,  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_BGE  = Uop(O.BGE,  srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b101))
UOP_BLTU = Uop(O.BLTU, srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b110))
UOP_BGEU = Uop(O.BGEU, srcs=_BR, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b111))

# --- I-type loads, opcode 0000011: rd = mem[rs1 + imm] -----------------------
UOP_LB  = Uop(O.LB,  srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_LH  = Uop(O.LH,  srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_LW  = Uop(O.LW,  srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))
UOP_LBU = Uop(O.LBU, srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_LHU = Uop(O.LHU, srcs=_ADDR, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b101))

# --- S-type stores, opcode 0100011: mem[rs1 + imm] = rs2 ---------------------
UOP_SB = Uop(O.SB, srcs=_STORE, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_SH = Uop(O.SH, srcs=_STORE, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_SW = Uop(O.SW, srcs=_STORE, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))

# --- I-type ALU, opcode 0010011: rd = rs1 op imm -----------------------------
UOP_ADDI  = Uop(O.ADD,  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_SLTI  = Uop(O.SLT,  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))
UOP_SLTIU = Uop(O.SLTU, srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b011))
UOP_XORI  = Uop(O.XOR,  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_ORI   = Uop(O.OR,   srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b110))
UOP_ANDI  = Uop(O.AND,  srcs=_IMM, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b111))

# Shift-immediate: funct3 picks the direction, funct7 logical vs arithmetic.
# Two segments in FUNCT3_7, so two values, funct3 first — that is the order
# FUNCT3_7 was unioned in (field_match.py).
UOP_SLLI = Uop(O.SLL, srcs=_SHIFT, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b001, 0b0000000))
UOP_SRLI = Uop(O.SRL, srcs=_SHIFT, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0000000))
UOP_SRAI = Uop(O.SRA, srcs=_SHIFT, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0100000))

# --- R-type, opcode 0110011: rd = rs1 op rs2 ---------------------------------
UOP_ADD  = Uop(O.ADD,  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b000, 0b0000000))
UOP_SUB  = Uop(O.SUB,  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b000, 0b0100000))
UOP_SLL  = Uop(O.SLL,  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b001))
UOP_SLT  = Uop(O.SLT,  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b010))
UOP_SLTU = Uop(O.SLTU, srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b011))
UOP_XOR  = Uop(O.XOR,  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b100))
UOP_SRL  = Uop(O.SRL,  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0000000))
UOP_SRA  = Uop(O.SRA,  srcs=_REG, dests=_RD,
               matcher_field=FM.FUNCT3_7, matcher_value=FM.val(0b101, 0b0100000))
UOP_OR   = Uop(O.OR,   srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b110))
UOP_AND  = Uop(O.AND,  srcs=_REG, dests=_RD, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b111))

# --- outside the base listing above, but part of RV32I -----------------------
# ecall and ebreak share opcode 1110011 AND funct3 000; the whole imm[11:0] is
# what tells them apart, which is why their matcher is IMM_I and not FUNCT3.
UOP_FENCE  = Uop(O.FENCE, matcher_field=FM.FUNCT3, matcher_value=FM.val(0b000))
UOP_ECALL  = Uop(O.TRAP,  matcher_field=FM.IMM_I, matcher_value=FM.val(0b000000000000))
UOP_EBREAK = Uop(O.TRAP,  matcher_field=FM.IMM_I, matcher_value=FM.val(0b000000000001))

UOPS = (UOP_LUI, UOP_AUIPC, UOP_JAL, UOP_JALR,
        UOP_BEQ, UOP_BNE, UOP_BLT, UOP_BGE, UOP_BLTU, UOP_BGEU,
        UOP_LB, UOP_LH, UOP_LW, UOP_LBU, UOP_LHU,
        UOP_SB, UOP_SH, UOP_SW,
        UOP_ADDI, UOP_SLTI, UOP_SLTIU, UOP_XORI, UOP_ORI, UOP_ANDI,
        UOP_SLLI, UOP_SRLI, UOP_SRAI,
        UOP_ADD, UOP_SUB, UOP_SLL, UOP_SLT, UOP_SLTU, UOP_XOR,
        UOP_SRL, UOP_SRA, UOP_OR, UOP_AND,
        UOP_FENCE, UOP_ECALL, UOP_EBREAK)
