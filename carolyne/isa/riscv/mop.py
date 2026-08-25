# The RV32I instruction table: one Mop per opcode group, one UopSeq per
# instruction in that group (uop_contract.md §6.4). This file is the ENCODING
# side whole — the opcode grouping AND the funct matcher that picks each
# UopSeq out of its group. What an instruction does is uop.py's business
# (a template carries no matcher), and the IsaBase assembly is rv32i.py's.
#
# The Mop/UopSeq nesting mirrors RISC-V's own decode shape: the Mop matches
# an opcode (stated as a matcher_value beside FM.OPCODE), each UopSeq the
# finer funct rule.
#
# Grouped by OPCODE, not by instruction format — the two are different
# partitions, since I-type covers LOAD, OP-IMM, JALR and SYSTEM, and one
# matcher naming the opcode field cannot say four values. Each group names its
# format in a comment; field_match.FORMATS is declared but not yet consumed.
#
# Every UopSeq holds one µop, because RV32I cracks nothing. An
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

from typing import Optional

from ..field_match import InstrFieldMatch
from ..mop import Mop, UopSeq
from ..uop import Uop
from . import field_match as FM
from . import uop as U


def _bind(uop: Uop, matcher_field: Optional[InstrFieldMatch] = None,
          *values: int) -> UopSeq:
    """Bind one µop to the funct rule that picks it out of its opcode group.

    - no field, no values -> the opcode alone identifies it (LUI/AUIPC/JAL)
    - values in the field's own segment order, reading like the spec table
    """
    return UopSeq(uops=(uop,),
                  matcher_field=matcher_field,
                  matcher_value=FM.val(*values) if values else None)

# opcode 0110011 — OP, R-type: rd = rs1 op rs2. add/sub and srl/sra share a
# funct3 and differ only in funct7, so their rule spans both (FM.FUNCT3_7).
MOP_OP = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0110011), uop_seq=(
    _bind(U.UOP_ADD,  FM.FUNCT3_7, 0b000, 0b0000000),
    _bind(U.UOP_SUB,  FM.FUNCT3_7, 0b000, 0b0100000),
    _bind(U.UOP_SLL,  FM.FUNCT3,   0b001),
    _bind(U.UOP_SLT,  FM.FUNCT3,   0b010),
    _bind(U.UOP_SLTU, FM.FUNCT3,   0b011),
    _bind(U.UOP_XOR,  FM.FUNCT3,   0b100),
    _bind(U.UOP_SRL,  FM.FUNCT3_7, 0b101, 0b0000000),
    _bind(U.UOP_SRA,  FM.FUNCT3_7, 0b101, 0b0100000),
    _bind(U.UOP_OR,   FM.FUNCT3,   0b110),
    _bind(U.UOP_AND,  FM.FUNCT3,   0b111),
))

# opcode 0010011 — OP-IMM, I-type: rd = rs1 op imm. The three shifts are
# I-type too, with imm[11:0] read as funct7|shamt — their rule spans both.
MOP_OP_IMM = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0010011), uop_seq=(
    _bind(U.UOP_ADDI,  FM.FUNCT3,   0b000),
    _bind(U.UOP_SLTI,  FM.FUNCT3,   0b010),
    _bind(U.UOP_SLTIU, FM.FUNCT3,   0b011),
    _bind(U.UOP_XORI,  FM.FUNCT3,   0b100),
    _bind(U.UOP_ORI,   FM.FUNCT3,   0b110),
    _bind(U.UOP_ANDI,  FM.FUNCT3,   0b111),
    _bind(U.UOP_SLLI,  FM.FUNCT3_7, 0b001, 0b0000000),
    _bind(U.UOP_SRLI,  FM.FUNCT3_7, 0b101, 0b0000000),
    _bind(U.UOP_SRAI,  FM.FUNCT3_7, 0b101, 0b0100000),
))

# opcode 0000011 — LOAD, I-type: rd = mem[rs1 + imm]; width/sign is the op
MOP_LOAD = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0000011), uop_seq=(
    _bind(U.UOP_LB,  FM.FUNCT3, 0b000),
    _bind(U.UOP_LH,  FM.FUNCT3, 0b001),
    _bind(U.UOP_LW,  FM.FUNCT3, 0b010),
    _bind(U.UOP_LBU, FM.FUNCT3, 0b100),
    _bind(U.UOP_LHU, FM.FUNCT3, 0b101),
))

# opcode 0100011 — STORE, S-type: mem[rs1 + imm] = rs2; width is the op
MOP_STORE = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0100011), uop_seq=(
    _bind(U.UOP_SB, FM.FUNCT3, 0b000),
    _bind(U.UOP_SH, FM.FUNCT3, 0b001),
    _bind(U.UOP_SW, FM.FUNCT3, 0b010),
))

# opcode 1100011 — BRANCH, B-type; the condition is the op
MOP_BRANCH = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1100011), uop_seq=(
    _bind(U.UOP_BEQ,  FM.FUNCT3, 0b000),
    _bind(U.UOP_BNE,  FM.FUNCT3, 0b001),
    _bind(U.UOP_BLT,  FM.FUNCT3, 0b100),
    _bind(U.UOP_BGE,  FM.FUNCT3, 0b101),
    _bind(U.UOP_BLTU, FM.FUNCT3, 0b110),
    _bind(U.UOP_BGEU, FM.FUNCT3, 0b111),
))

# opcodes 0110111 / 0010111 — LUI / AUIPC, both U-type; opcode alone decides
MOP_LUI   = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0110111),
                uop_seq=(_bind(U.UOP_LUI),))
MOP_AUIPC = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0010111),
                uop_seq=(_bind(U.UOP_AUIPC),))

# opcodes 1101111 / 1100111 — JAL (J-type) / JALR (I-type)
MOP_JAL  = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1101111),
               uop_seq=(_bind(U.UOP_JAL),))
MOP_JALR = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1100111),
               uop_seq=(_bind(U.UOP_JALR, FM.FUNCT3, 0b000),))

# opcodes 0001111 / 1110011 — MISC-MEM (fence) / SYSTEM (ecall, ebreak),
# both I-type: fence's operands sit in imm[11:0], ecall/ebreak's imm IS the
# selector, which is why their UopSeqs match on IMM_I and not FUNCT3.
MOP_MISC_MEM = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b0001111),
                   uop_seq=(_bind(U.UOP_FENCE, FM.FUNCT3, 0b000),))
MOP_SYSTEM   = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b1110011), uop_seq=(
    _bind(U.UOP_ECALL,  FM.IMM_I, 0b000000000000),
    _bind(U.UOP_EBREAK, FM.IMM_I, 0b000000000001),
))

# Every RV32I instruction group, as Mops over the µop templates of uop.py.
MOP_TABLE = (MOP_OP, MOP_OP_IMM, MOP_LOAD, MOP_STORE, MOP_BRANCH,
             MOP_LUI, MOP_AUIPC, MOP_JAL, MOP_JALR, MOP_MISC_MEM, MOP_SYSTEM)
