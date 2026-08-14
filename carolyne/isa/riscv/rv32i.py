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
# - The per-format shape builders live HERE, as the `_rtype`/`_load`/... helpers
#   below; each returns a finished UopSeq built from the operand slots of
#   operand.py and the field positions of field_match.py. They were a separate
#   cracks.py for as long as a format could produce several µops; now that RV32I
#   cracks nothing (no AGU, and the jumps write their own link register), a
#   whole module of one-line factories was indirection between the table and
#   the shape it names. If a format ever cracks again, it grows back
#   into its own file — and then a builder must mint its own Intermediate per
#   call, never share one, because that instance IS the dataflow link between
#   the µops of one instruction.
# - `rv32i()` is a factory returning IsaBase, not an IsaBase subclass: RV32I
#   has no description fields the container does not already model, and a
#   factory keeps every ISA the same type downstream (isa.py header).
# - The shapes name the shared operand constants of operand.py, which target
#   the shared register class regs.RegFile — and `rv32i()` declares that same
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
# 3. No immediates on Uop — the field was removed while the matcher design is
#    in flight, so every shape is missing one: addi's imm12, the load/store
#    displacement, the branch/jal targets, lui's constant. Marked `# imm:`.
# 4. PC is not a register class (regs.py), so the pc-relative shapes — auipc,
#    and the link value the jumps write — have an input this layer cannot
#    name: the instruction's own PC. Written with that source ABSENT, marked
#    `# pc:`. The contract needs to say a µop reads its instruction PC from
#    the record; until then these shapes are incomplete in a way the
#    container's cross-checks cannot catch.
# 5. The branch µops name no destination and the jumps' redirect is invisible
#    here: control-flow effect is the FU's business, not register dataflow.
# Only the register dataflow and the unit routing are complete and checkable.
# Two former gaps are closed rather than open: mem width/sign and branch
# condition are distinct ops rather than record sub-fields (ops.py header),
# and first/last bounds are moot while every instruction is one µop — both
# return with x86mini.

from __future__ import annotations

from typing import Tuple

from ..isa import IsaBase
from ..mop import InstrFieldMatch, Mop, UopSeq
from ..uop import Uop
from . import field_match as FM
from . import ops as O
from .operand import OPR_RD, OPR_RS1, OPR_RS2
from .ops import OPS, exec_units
from .regs import RegFile


# --- one shape builder per instruction format, each a single µop ------------
# The `# imm:` comments name the immediate operand each shape will carry once
# Uop has an `imm` field again (operand.py); the register dataflow is done.

def _rtype(op, matcher: InstrFieldMatch) -> UopSeq:
    """add/sub/and/or/xor/sll/srl/sra/slt/sltu — rd = rs1 op rs2."""
    return UopSeq(uops=(Uop(op, srcs=(OPR_RS1, OPR_RS2), dests=(OPR_RD,)),), matcher=matcher)


def _itype(op, matcher: InstrFieldMatch) -> UopSeq:
    """addi/andi/ori/xori/slti/sltiu/slli/srli/srai — rd = rs1 op imm."""
    return UopSeq(uops=(Uop(op, srcs=(OPR_RS1,), dests=(OPR_RD,)),),     # imm: OPR_IMM_I / OPR_IMM_SHAMT
                  matcher=matcher)


def _load(op, matcher: InstrFieldMatch) -> UopSeq:
    """lb/lh/lw/lbu/lhu — rd = mem[rs1 + imm]; width and sign ride in `op`."""
    return UopSeq(uops=(Uop(op, srcs=(OPR_RS1,), dests=(OPR_RD,)),),     # imm: OPR_IMM_I
                  matcher=matcher)


def _store(op, matcher: InstrFieldMatch) -> UopSeq:
    """sb/sh/sw — mem[rs1 + imm] = rs2."""
    return UopSeq(uops=(Uop(op, srcs=(OPR_RS1, OPR_RS2)),),              # imm: OPR_IMM_S
                  matcher=matcher)


def _branch(op, matcher: InstrFieldMatch) -> UopSeq:
    """beq/bne/blt/bge/bltu/bgeu — the test is the op; no destination."""
    return UopSeq(uops=(Uop(op, srcs=(OPR_RS1, OPR_RS2)),),              # imm: OPR_IMM_B
                  matcher=matcher)                               # pc: target is relative


def _lui(matcher: InstrFieldMatch) -> UopSeq:
    """lui — rd = imm << 12, no register source."""
    return UopSeq(uops=(Uop(O.MOV_IMM, dests=(OPR_RD,)),),           # imm: OPR_IMM_U
                  matcher=matcher)


def _auipc(matcher: InstrFieldMatch) -> UopSeq:
    """auipc — rd = pc + (imm << 12)."""
    return UopSeq(uops=(Uop(O.AUIPC, dests=(OPR_RD,)),),             # imm: OPR_IMM_U
                  matcher=matcher)                               # pc: the missing source


def _jal(matcher: InstrFieldMatch) -> UopSeq:
    """jal — rd = pc + ilen and redirect to pc + imm, in one µop."""
    return UopSeq(uops=(Uop(O.JMP, dests=(OPR_RD,)),),               # imm: OPR_IMM_J
                  matcher=matcher)                               # pc: link and target


def _jalr(matcher: InstrFieldMatch) -> UopSeq:
    """jalr — rd = pc + ilen and redirect to (rs1 + imm) & ~1, in one µop."""
    return UopSeq(uops=(Uop(O.JMP_INDIRECT, srcs=(OPR_RS1,), dests=(OPR_RD,)),),  # imm: OPR_IMM_I
                  matcher=matcher)                                        # pc: link value


def _system(op, matcher: InstrFieldMatch) -> UopSeq:
    """fence / ecall / ebreak — ordering and traps, no register dataflow."""
    return UopSeq(uops=(Uop(op),), matcher=matcher)


# --- the table --------------------------------------------------------------

def mop_table() -> Tuple[Mop, ...]:
    """Every RV32I instruction group, as Mops over the shared operand rules."""

    # opcode 0110011 — OP: rd = rs1 op rs2
    op_group = Mop(matcher=FM.OPCODE, uop_seq=(
        _rtype(O.ADD,  FM.FUNCT7),    # funct3 000, funct7 0000000
        _rtype(O.SUB,  FM.FUNCT7),    # funct3 000, funct7 0100000
        _rtype(O.SLL,  FM.FUNCT3),    # funct3 001
        _rtype(O.SLT,  FM.FUNCT3),    # funct3 010
        _rtype(O.SLTU, FM.FUNCT3),    # funct3 011
        _rtype(O.XOR,  FM.FUNCT3),    # funct3 100
        _rtype(O.SRL,  FM.FUNCT7),    # funct3 101, funct7 0000000
        _rtype(O.SRA,  FM.FUNCT7),    # funct3 101, funct7 0100000
        _rtype(O.OR,   FM.FUNCT3),    # funct3 110
        _rtype(O.AND,  FM.FUNCT3),    # funct3 111
    ))

    # opcode 0010011 — OP-IMM: rd = rs1 op imm
    op_imm_group = Mop(matcher=FM.OPCODE, uop_seq=(
        _itype(O.ADD,  FM.FUNCT3),    # addi,  funct3 000
        _itype(O.SLT,  FM.FUNCT3),    # slti,  funct3 010
        _itype(O.SLTU, FM.FUNCT3),    # sltiu, funct3 011
        _itype(O.XOR,  FM.FUNCT3),    # xori,  funct3 100
        _itype(O.OR,   FM.FUNCT3),    # ori,   funct3 110
        _itype(O.AND,  FM.FUNCT3),    # andi,  funct3 111
        _itype(O.SLL,  FM.SHAMT),     # slli,  funct3 001
        _itype(O.SRL,  FM.SHAMT),     # srli,  funct3 101, funct7 0000000
        _itype(O.SRA,  FM.SHAMT),     # srai,  funct3 101, funct7 0100000
    ))

    # opcode 0000011 — LOAD: rd = mem[rs1 + imm]; width/sign is the op
    load_group = Mop(matcher=FM.OPCODE, uop_seq=(
        _load(O.LB,  FM.FUNCT3),      # funct3 000
        _load(O.LH,  FM.FUNCT3),      # funct3 001
        _load(O.LW,  FM.FUNCT3),      # funct3 010
        _load(O.LBU, FM.FUNCT3),      # funct3 100
        _load(O.LHU, FM.FUNCT3),      # funct3 101
    ))

    # opcode 0100011 — STORE: mem[rs1 + imm] = rs2; width is the op
    store_group = Mop(matcher=FM.OPCODE, uop_seq=(
        _store(O.SB, FM.FUNCT3),      # funct3 000
        _store(O.SH, FM.FUNCT3),      # funct3 001
        _store(O.SW, FM.FUNCT3),      # funct3 010
    ))

    # opcode 1100011 — BRANCH; the condition is the op
    branch_group = Mop(matcher=FM.OPCODE, uop_seq=(
        _branch(O.BEQ,  FM.FUNCT3),   # funct3 000
        _branch(O.BNE,  FM.FUNCT3),   # funct3 001
        _branch(O.BLT,  FM.FUNCT3),   # funct3 100
        _branch(O.BGE,  FM.FUNCT3),   # funct3 101
        _branch(O.BLTU, FM.FUNCT3),   # funct3 110
        _branch(O.BGEU, FM.FUNCT3),   # funct3 111
    ))

    # opcodes 0110111 / 0010111 — LUI / AUIPC
    lui   = Mop(matcher=FM.OPCODE, uop_seq=(_lui(FM.IMM_U),))
    auipc = Mop(matcher=FM.OPCODE, uop_seq=(_auipc(FM.IMM_U),))

    # opcodes 1101111 / 1100111 — JAL / JALR
    jal  = Mop(matcher=FM.OPCODE, uop_seq=(_jal(FM.IMM_J),))
    jalr = Mop(matcher=FM.OPCODE, uop_seq=(_jalr(FM.FUNCT3),))

    # opcodes 0001111 / 1110011 — MISC-MEM (fence) / SYSTEM (ecall, ebreak)
    misc_mem = Mop(matcher=FM.OPCODE, uop_seq=(_system(O.FENCE, FM.FUNCT3),))
    system   = Mop(matcher=FM.OPCODE, uop_seq=(_system(O.TRAP,  FM.IMM_I),))

    return (op_group, op_imm_group, load_group, store_group, branch_group,
            lui, auipc, jal, jalr, misc_mem, system)


def rv32i() -> IsaBase:
    """The RV32I description — the object a generator is handed."""
    return IsaBase(name="rv32i",
                   reg_files=(RegFile,),  # the instance operand.py's rules target
                   ops=OPS,
                   exec_units=exec_units(),
                   mops=mop_table())
