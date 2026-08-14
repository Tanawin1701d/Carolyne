# The RV32I instruction table: one Mop per opcode group, one UopSeq variant
# per instruction in that group, and the IsaBase that ties the four
# vocabularies together (uop_contract.md §6).
#
# Decisions (2026-08-14):
# - The Mop/UopSeq nesting mirrors RISC-V's own decode shape: the Mop matches
#   the opcode, each UopSeq variant matches the funct field that picks one
#   instruction out of the group. That is why the group comments below name
#   the funct values — they are the ISA's real content, even though the type
#   cannot carry them yet (see GAPS).
# - This file is the ENCODING side only. Each variant names a µop template
#   from uop.py; the dataflow of an instruction is written down there, once.
#   The split follows the two questions a description answers: "which bits
#   select this instruction" (here) and "what does it do" (uop.py).
# - Every variant holds a one-µop sequence, because RV32I cracks nothing (no
#   AGU, and the jumps write their own link register). If an instruction ever
#   does crack, its UopSeq lists several templates — and any µtemp linking
#   them must be minted per instruction, never shared, since that instance IS
#   the dataflow link.
# - `rv32i()` is a factory returning IsaBase, not an IsaBase subclass: RV32I
#   has no description fields the container does not already model, and a
#   factory keeps every ISA the same type downstream (isa.py header).
# - The shapes name the shared operand constants of operand.py, which target
#   the shared register class reg.RegFile — and `rv32i()` declares that same
#   instance.
#   IsaBase matches reg files by identity, so those two must be one object;
#   sharing module constants is what makes that true by construction (and is
#   why the builders take no register-class argument).
#
# KNOWN GAPS — what this table cannot say yet, all of them contract-side:
# 1. No field VALUES. InstrFieldMatch names bit positions only, so "opcode ==
#    0110011" is unsayable and the variants below are not actually
#    distinguishable. The funct values live in comments as a placeholder.
# 2. One matcher per level. add vs sub share funct3=000 and differ only in
#    funct7, so an R-type variant genuinely needs TWO field matches; today a
#    UopSeq carries one.
# 3. No `imm` field on Uop, so the immediates ride in `srcs` as operands
#    (uop.py header) — which contract §2 says they should not. One of the two
#    has to give before the µop record is generated.
# 4. PC is not a register class (reg.py), so the pc-relative shapes — auipc,
#    and the link value the jumps write — have an input this layer cannot
#    name: the instruction's own PC. Written with that source ABSENT, marked
#    `# pc:`. The contract needs to say a µop reads its instruction PC from
#    the record; until then these shapes are incomplete in a way the
#    container's cross-checks cannot catch.
# 5. The branch µops name no destination and the jumps' redirect is invisible
#    here: control-flow effect is the FU's business, not register dataflow.
# Only the register dataflow and the unit routing are complete and checkable.
# Two former gaps are closed rather than open: mem width/sign and branch
# condition are distinct ops rather than record sub-fields (op.py header),
# and first/last bounds are moot while every instruction is one µop — both
# return with x86mini.

from __future__ import annotations

from typing import Tuple

from ..isa import IsaBase
from ..mop import Mop, UopSeq
from . import field_match as FM
from . import uop as U
from .op import OPS, exec_units
from .reg import RegFile


# --- the table --------------------------------------------------------------

def mop_table() -> Tuple[Mop, ...]:
    """Every RV32I instruction group, as Mops over the µop templates of uop.py."""

    # opcode 0110011 — OP: rd = rs1 op rs2
    op_group = Mop(matcher=FM.OPCODE, uop_seq=(
        UopSeq(uops=(U.UOP_ADD,),  matcher=FM.FUNCT7),   # funct3 000, funct7 0000000
        UopSeq(uops=(U.UOP_SUB,),  matcher=FM.FUNCT7),   # funct3 000, funct7 0100000
        UopSeq(uops=(U.UOP_SLL,),  matcher=FM.FUNCT3),   # funct3 001
        UopSeq(uops=(U.UOP_SLT,),  matcher=FM.FUNCT3),   # funct3 010
        UopSeq(uops=(U.UOP_SLTU,), matcher=FM.FUNCT3),   # funct3 011
        UopSeq(uops=(U.UOP_XOR,),  matcher=FM.FUNCT3),   # funct3 100
        UopSeq(uops=(U.UOP_SRL,),  matcher=FM.FUNCT7),   # funct3 101, funct7 0000000
        UopSeq(uops=(U.UOP_SRA,),  matcher=FM.FUNCT7),   # funct3 101, funct7 0100000
        UopSeq(uops=(U.UOP_OR,),   matcher=FM.FUNCT3),   # funct3 110
        UopSeq(uops=(U.UOP_AND,),  matcher=FM.FUNCT3),   # funct3 111
    ))

    # opcode 0010011 — OP-IMM: rd = rs1 op imm
    op_imm_group = Mop(matcher=FM.OPCODE, uop_seq=(
        UopSeq(uops=(U.UOP_ADDI,),  matcher=FM.FUNCT3),  # funct3 000
        UopSeq(uops=(U.UOP_SLTI,),  matcher=FM.FUNCT3),  # funct3 010
        UopSeq(uops=(U.UOP_SLTIU,), matcher=FM.FUNCT3),  # funct3 011
        UopSeq(uops=(U.UOP_XORI,),  matcher=FM.FUNCT3),  # funct3 100
        UopSeq(uops=(U.UOP_ORI,),   matcher=FM.FUNCT3),  # funct3 110
        UopSeq(uops=(U.UOP_ANDI,),  matcher=FM.FUNCT3),  # funct3 111
        UopSeq(uops=(U.UOP_SLLI,),  matcher=FM.FUNCT7),  # funct3 001, funct7 0000000
        UopSeq(uops=(U.UOP_SRLI,),  matcher=FM.FUNCT7),  # funct3 101, funct7 0000000
        UopSeq(uops=(U.UOP_SRAI,),  matcher=FM.FUNCT7),  # funct3 101, funct7 0100000
    ))

    # opcode 0000011 — LOAD: rd = mem[rs1 + imm]; width/sign is the op
    load_group = Mop(matcher=FM.OPCODE, uop_seq=(
        UopSeq(uops=(U.UOP_LB,),  matcher=FM.FUNCT3),    # funct3 000
        UopSeq(uops=(U.UOP_LH,),  matcher=FM.FUNCT3),    # funct3 001
        UopSeq(uops=(U.UOP_LW,),  matcher=FM.FUNCT3),    # funct3 010
        UopSeq(uops=(U.UOP_LBU,), matcher=FM.FUNCT3),    # funct3 100
        UopSeq(uops=(U.UOP_LHU,), matcher=FM.FUNCT3),    # funct3 101
    ))

    # opcode 0100011 — STORE: mem[rs1 + imm] = rs2; width is the op
    store_group = Mop(matcher=FM.OPCODE, uop_seq=(
        UopSeq(uops=(U.UOP_SB,), matcher=FM.FUNCT3),     # funct3 000
        UopSeq(uops=(U.UOP_SH,), matcher=FM.FUNCT3),     # funct3 001
        UopSeq(uops=(U.UOP_SW,), matcher=FM.FUNCT3),     # funct3 010
    ))

    # opcode 1100011 — BRANCH; the condition is the op
    branch_group = Mop(matcher=FM.OPCODE, uop_seq=(
        UopSeq(uops=(U.UOP_BEQ,),  matcher=FM.FUNCT3),   # funct3 000
        UopSeq(uops=(U.UOP_BNE,),  matcher=FM.FUNCT3),   # funct3 001
        UopSeq(uops=(U.UOP_BLT,),  matcher=FM.FUNCT3),   # funct3 100
        UopSeq(uops=(U.UOP_BGE,),  matcher=FM.FUNCT3),   # funct3 101
        UopSeq(uops=(U.UOP_BLTU,), matcher=FM.FUNCT3),   # funct3 110
        UopSeq(uops=(U.UOP_BGEU,), matcher=FM.FUNCT3),   # funct3 111
    ))

    # opcodes 0110111 / 0010111 — LUI / AUIPC
    lui   = Mop(matcher=FM.OPCODE, uop_seq=(UopSeq(uops=(U.UOP_LUI,),   matcher=FM.IMM_U),))
    auipc = Mop(matcher=FM.OPCODE, uop_seq=(UopSeq(uops=(U.UOP_AUIPC,), matcher=FM.IMM_U),))

    # opcodes 1101111 / 1100111 — JAL / JALR
    jal  = Mop(matcher=FM.OPCODE, uop_seq=(UopSeq(uops=(U.UOP_JAL,),  matcher=FM.IMM_J),))
    jalr = Mop(matcher=FM.OPCODE, uop_seq=(UopSeq(uops=(U.UOP_JALR,), matcher=FM.FUNCT3),))

    # opcodes 0001111 / 1110011 — MISC-MEM (fence) / SYSTEM (ecall, ebreak)
    misc_mem = Mop(matcher=FM.OPCODE, uop_seq=(UopSeq(uops=(U.UOP_FENCE,), matcher=FM.FUNCT3),))
    system   = Mop(matcher=FM.OPCODE, uop_seq=(
        UopSeq(uops=(U.UOP_ECALL,),  matcher=FM.IMM_I),  # imm 000000000000
        UopSeq(uops=(U.UOP_EBREAK,), matcher=FM.IMM_I),  # imm 000000000001
    ))

    return (op_group, op_imm_group, load_group, store_group, branch_group,
            lui, auipc, jal, jalr, misc_mem, system)


def rv32i() -> IsaBase:
    """The RV32I description — the object a generator is handed."""
    return IsaBase(name="rv32i",
                   reg_files=(RegFile,),  # the instance operand.py's rules target
                   ops=OPS,
                   exec_units=exec_units(),
                   mops=mop_table())
