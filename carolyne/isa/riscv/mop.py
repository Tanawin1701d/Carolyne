# The RV32I instruction table: one Mop per opcode group, one UopSeq variant per
# instruction in that group (uop_contract.md §6.4). This file is the ENCODING
# grouping and nothing else — what an instruction does is uop.py's business,
# and the IsaBase assembly is rv32i.py's.
#
# The Mop/UopSeq nesting mirrors RISC-V's own decode shape: the Mop matches an
# opcode (stated as a matcher_value beside FM.OPCODE), and each UopSeq variant
# is picked by the funct matcher declared on the template itself (uop.py), so a
# fact about SRAI lives with SRAI.
#
# Grouped by OPCODE, not by instruction format — the two are different
# partitions, since I-type covers LOAD, OP-IMM, JALR and SYSTEM, and one
# matcher naming the opcode field cannot say four values. Each group names its
# format in a comment; field_match.FORMATS is declared but not yet consumed.
#
# Every variant holds a one-µop sequence, because RV32I cracks nothing. An
# instruction that does crack lists several templates, and any µtemp linking
# them must be minted per instruction, never shared — that instance IS the
# dataflow link.
#
# Exhaustive over uop.UOPS: every template appears in exactly one UopSeq,
# pinned by test_riscv.py, since no container check catches an instruction
# written but never wrapped in an encoding. Module CONSTANTS (MOP_<group> +
# MOP_TABLE), shared like the reg file and the operand constants.
#
# KNOWN GAPS — what this table cannot say yet, all of them contract-side:
# 1. No `imm` field on Uop, so the immediates ride in `srcs` as operands
#    (uop.py header) — which contract §2 says they should not. One of the two
#    has to give before the µop record is generated.
# 2. PC is not a register class (reg.py), so the pc-relative shapes — auipc,
#    and the link value the jumps write — have an input this layer cannot
#    name: the instruction's own PC. The contract needs to say a µop reads its
#    instruction PC from the record; until then these shapes are incomplete in
#    a way the container's cross-checks cannot catch.
# 3. The branch µops name no destination and the jumps' redirect is invisible
#    here: control-flow effect is the FU's business, not register dataflow.
# 4. A matcher discriminates but does not EXTRACT: nothing says where each
#    segment of a scrambled immediate lands in the assembled value, so a
#    decoder can pick the instruction and still not build its immediate
#    (field_match.py).
# Three former gaps are closed rather than open: field values (both levels
# state them now), mem width/sign and branch condition being distinct ops
# rather than record sub-fields (op.py header), and first/last bounds, moot
# while every instruction is one µop — the last returns with x86mini.

from __future__ import annotations

from ..mop import Mop, UopSeq
from . import field_match as FM
from . import uop as U

# opcode 0110011 — OP, R-type: rd = rs1 op rs2
MOP_OP = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0110011), uop_seq=(
    UopSeq(uops=(U.UOP_ADD,)),          # funct3 000, funct7 0000000
    UopSeq(uops=(U.UOP_SUB,)),          # funct3 000, funct7 0100000
    UopSeq(uops=(U.UOP_SLL,)),          # funct3 001
    UopSeq(uops=(U.UOP_SLT,)),          # funct3 010
    UopSeq(uops=(U.UOP_SLTU,)),         # funct3 011
    UopSeq(uops=(U.UOP_XOR,)),          # funct3 100
    UopSeq(uops=(U.UOP_SRL,)),          # funct3 101, funct7 0000000
    UopSeq(uops=(U.UOP_SRA,)),          # funct3 101, funct7 0100000
    UopSeq(uops=(U.UOP_OR,)),           # funct3 110
    UopSeq(uops=(U.UOP_AND,)),          # funct3 111
))

# opcode 0010011 — OP-IMM, I-type: rd = rs1 op imm. The three shifts are
# I-type too, with imm[11:0] read as funct7|shamt.
MOP_OP_IMM = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0010011), uop_seq=(
    UopSeq(uops=(U.UOP_ADDI,)),         # funct3 000
    UopSeq(uops=(U.UOP_SLTI,)),         # funct3 010
    UopSeq(uops=(U.UOP_SLTIU,)),        # funct3 011
    UopSeq(uops=(U.UOP_XORI,)),         # funct3 100
    UopSeq(uops=(U.UOP_ORI,)),          # funct3 110
    UopSeq(uops=(U.UOP_ANDI,)),         # funct3 111
    UopSeq(uops=(U.UOP_SLLI,)),         # funct3 001, funct7 0000000
    UopSeq(uops=(U.UOP_SRLI,)),         # funct3 101, funct7 0000000
    UopSeq(uops=(U.UOP_SRAI,)),         # funct3 101, funct7 0100000
))

# opcode 0000011 — LOAD, I-type: rd = mem[rs1 + imm]; width/sign is the op
MOP_LOAD = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0000011), uop_seq=(
    UopSeq(uops=(U.UOP_LB,)),           # funct3 000
    UopSeq(uops=(U.UOP_LH,)),           # funct3 001
    UopSeq(uops=(U.UOP_LW,)),           # funct3 010
    UopSeq(uops=(U.UOP_LBU,)),          # funct3 100
    UopSeq(uops=(U.UOP_LHU,)),          # funct3 101
))

# opcode 0100011 — STORE, S-type: mem[rs1 + imm] = rs2; width is the op
MOP_STORE = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0100011), uop_seq=(
    UopSeq(uops=(U.UOP_SB,)),           # funct3 000
    UopSeq(uops=(U.UOP_SH,)),           # funct3 001
    UopSeq(uops=(U.UOP_SW,)),           # funct3 010
))

# opcode 1100011 — BRANCH, B-type; the condition is the op
MOP_BRANCH = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1100011), uop_seq=(
    UopSeq(uops=(U.UOP_BEQ,)),          # funct3 000
    UopSeq(uops=(U.UOP_BNE,)),          # funct3 001
    UopSeq(uops=(U.UOP_BLT,)),          # funct3 100
    UopSeq(uops=(U.UOP_BGE,)),          # funct3 101
    UopSeq(uops=(U.UOP_BLTU,)),         # funct3 110
    UopSeq(uops=(U.UOP_BGEU,)),         # funct3 111
))

# opcodes 0110111 / 0010111 — LUI / AUIPC, both U-type; opcode alone decides
MOP_LUI   = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0110111), uop_seq=(UopSeq(uops=(U.UOP_LUI,)),))
MOP_AUIPC = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0010111), uop_seq=(UopSeq(uops=(U.UOP_AUIPC,)),))

# opcodes 1101111 / 1100111 — JAL (J-type) / JALR (I-type)
MOP_JAL  = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1101111), uop_seq=(UopSeq(uops=(U.UOP_JAL,)),))
MOP_JALR = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1100111), uop_seq=(UopSeq(uops=(U.UOP_JALR,)),))

# opcodes 0001111 / 1110011 — MISC-MEM (fence) / SYSTEM (ecall, ebreak),
# both I-type: fence's operands sit in imm[11:0], ecall/ebreak's imm IS the
# selector, which is why UOP_ECALL/UOP_EBREAK match on IMM_I.
MOP_MISC_MEM = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0001111), uop_seq=(UopSeq(uops=(U.UOP_FENCE,)),))
MOP_SYSTEM   = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1110011), uop_seq=(
    UopSeq(uops=(U.UOP_ECALL,)),        # imm 000000000000
    UopSeq(uops=(U.UOP_EBREAK,)),       # imm 000000000001
))

# Every RV32I instruction group, as Mops over the µop templates of uop.py.
MOP_TABLE = (MOP_OP, MOP_OP_IMM, MOP_LOAD, MOP_STORE, MOP_BRANCH,
             MOP_LUI, MOP_AUIPC, MOP_JAL, MOP_JALR, MOP_MISC_MEM, MOP_SYSTEM)
