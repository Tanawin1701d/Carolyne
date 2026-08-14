# One Uop template per RV32I instruction — the µop an instruction decodes to,
# transcribed from the RV32I base listing (RISC-V unprivileged spec, ch. 36).
# Every instruction is exactly ONE µop here: RV32I has no AGU (addressing is
# base+imm, computed in the mem unit) and no separate link µop (the jumps
# write rd themselves), so nothing cracks. See the rv32i.py header.
#
# Decisions (2026-08-14):
# - Module CONSTANTS named UOP_<mnemonic>, one per row of the listing, so the
#   table in rv32i.py reads as encodings → named instructions and this file
#   is the one place an instruction's dataflow is written down. The comment
#   on each line carries its encoding (funct7 / funct3 / opcode), which the
#   types cannot yet hold — InstrFieldMatch has no VALUE field.
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
# - No encoding VALUES, so nothing here is actually decodable yet; the funct
#   comments are what the matcher will eventually hold.
# - auipc, jal and jalr need the instruction's own PC as an input, which no
#   operand can name (reg.py: PC is not a register class). Their `srcs` are
#   the encoding's operands only.
# - The branch/jump redirect is not expressed: the control FU takes it from
#   the op plus the immediate, and no dest names it.

from __future__ import annotations

from ..uop import Uop
from . import op as O
from .operand import (OPR_IMM_B, OPR_IMM_I, OPR_IMM_J, OPR_IMM_S,
                      OPR_IMM_SHAMT, OPR_IMM_U, OPR_RD, OPR_RS1, OPR_RS2)

# --- U-type: rd = imm ---------------------------------------------------------
#                                                              imm[31:12] rd opcode
UOP_LUI   = Uop(O.MOV_IMM, srcs=(OPR_IMM_U,), dests=(OPR_RD,))      # 0110111
UOP_AUIPC = Uop(O.AUIPC,   srcs=(OPR_IMM_U,), dests=(OPR_RD,))      # 0010111

# --- J-type / I-type jumps: rd = pc + ilen, then redirect ---------------------
UOP_JAL  = Uop(O.JMP,          srcs=(OPR_IMM_J,), dests=(OPR_RD,))  # 1101111
UOP_JALR = Uop(O.JMP_INDIRECT, srcs=(OPR_RS1, OPR_IMM_I),           # 1100111, funct3 000
               dests=(OPR_RD,))

# --- B-type: redirect to pc + imm when the test holds; no destination --------
_BRANCH = (OPR_RS1, OPR_RS2, OPR_IMM_B)                             # opcode 1100011
UOP_BEQ  = Uop(O.BEQ,  srcs=_BRANCH)                                # funct3 000
UOP_BNE  = Uop(O.BNE,  srcs=_BRANCH)                                # funct3 001
UOP_BLT  = Uop(O.BLT,  srcs=_BRANCH)                                # funct3 100
UOP_BGE  = Uop(O.BGE,  srcs=_BRANCH)                                # funct3 101
UOP_BLTU = Uop(O.BLTU, srcs=_BRANCH)                                # funct3 110
UOP_BGEU = Uop(O.BGEU, srcs=_BRANCH)                                # funct3 111

# --- I-type loads: rd = mem[rs1 + imm] ---------------------------------------
_ADDR = (OPR_RS1, OPR_IMM_I)                                        # opcode 0000011
UOP_LB  = Uop(O.LB,  srcs=_ADDR, dests=(OPR_RD,))                   # funct3 000
UOP_LH  = Uop(O.LH,  srcs=_ADDR, dests=(OPR_RD,))                   # funct3 001
UOP_LW  = Uop(O.LW,  srcs=_ADDR, dests=(OPR_RD,))                   # funct3 010
UOP_LBU = Uop(O.LBU, srcs=_ADDR, dests=(OPR_RD,))                   # funct3 100
UOP_LHU = Uop(O.LHU, srcs=_ADDR, dests=(OPR_RD,))                   # funct3 101

# --- S-type stores: mem[rs1 + imm] = rs2 -------------------------------------
_STORE = (OPR_RS1, OPR_RS2, OPR_IMM_S)                              # opcode 0100011
UOP_SB = Uop(O.SB, srcs=_STORE)                                     # funct3 000
UOP_SH = Uop(O.SH, srcs=_STORE)                                     # funct3 001
UOP_SW = Uop(O.SW, srcs=_STORE)                                     # funct3 010

# --- I-type ALU: rd = rs1 op imm ---------------------------------------------
_IMM_ALU = (OPR_RS1, OPR_IMM_I)                                     # opcode 0010011
UOP_ADDI  = Uop(O.ADD,  srcs=_IMM_ALU, dests=(OPR_RD,))             # funct3 000
UOP_SLTI  = Uop(O.SLT,  srcs=_IMM_ALU, dests=(OPR_RD,))             # funct3 010
UOP_SLTIU = Uop(O.SLTU, srcs=_IMM_ALU, dests=(OPR_RD,))             # funct3 011
UOP_XORI  = Uop(O.XOR,  srcs=_IMM_ALU, dests=(OPR_RD,))             # funct3 100
UOP_ORI   = Uop(O.OR,   srcs=_IMM_ALU, dests=(OPR_RD,))             # funct3 110
UOP_ANDI  = Uop(O.AND,  srcs=_IMM_ALU, dests=(OPR_RD,))             # funct3 111

# Shift-immediate: the count is 5 bits, and funct7 picks logical vs arithmetic.
_SHIFT_IMM = (OPR_RS1, OPR_IMM_SHAMT)
UOP_SLLI = Uop(O.SLL, srcs=_SHIFT_IMM, dests=(OPR_RD,))             # funct3 001, funct7 0000000
UOP_SRLI = Uop(O.SRL, srcs=_SHIFT_IMM, dests=(OPR_RD,))             # funct3 101, funct7 0000000
UOP_SRAI = Uop(O.SRA, srcs=_SHIFT_IMM, dests=(OPR_RD,))             # funct3 101, funct7 0100000

# --- R-type: rd = rs1 op rs2 --------------------------------------------------
_REG_ALU = (OPR_RS1, OPR_RS2)                                       # opcode 0110011
UOP_ADD  = Uop(O.ADD,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 000, funct7 0000000
UOP_SUB  = Uop(O.SUB,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 000, funct7 0100000
UOP_SLL  = Uop(O.SLL,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 001
UOP_SLT  = Uop(O.SLT,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 010
UOP_SLTU = Uop(O.SLTU, srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 011
UOP_XOR  = Uop(O.XOR,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 100
UOP_SRL  = Uop(O.SRL,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 101, funct7 0000000
UOP_SRA  = Uop(O.SRA,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 101, funct7 0100000
UOP_OR   = Uop(O.OR,   srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 110
UOP_AND  = Uop(O.AND,  srcs=_REG_ALU, dests=(OPR_RD,))              # funct3 111

# --- outside the base listing above, but part of RV32I -----------------------
UOP_FENCE  = Uop(O.FENCE)                                           # 0001111, funct3 000
UOP_ECALL  = Uop(O.TRAP)                                            # 1110011, imm 000000000000
UOP_EBREAK = Uop(O.TRAP)                                            # 1110011, imm 000000000001

UOPS = (UOP_LUI, UOP_AUIPC, UOP_JAL, UOP_JALR,
        UOP_BEQ, UOP_BNE, UOP_BLT, UOP_BGE, UOP_BLTU, UOP_BGEU,
        UOP_LB, UOP_LH, UOP_LW, UOP_LBU, UOP_LHU,
        UOP_SB, UOP_SH, UOP_SW,
        UOP_ADDI, UOP_SLTI, UOP_SLTIU, UOP_XORI, UOP_ORI, UOP_ANDI,
        UOP_SLLI, UOP_SRLI, UOP_SRAI,
        UOP_ADD, UOP_SUB, UOP_SLL, UOP_SLT, UOP_SLTU, UOP_XOR,
        UOP_SRL, UOP_SRA, UOP_OR, UOP_AND,
        UOP_FENCE, UOP_ECALL, UOP_EBREAK)
