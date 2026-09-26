# The MIPS32 instruction table: one Mop per opcode, one UopSeq per
# instruction under it (uop_contract.md §6.4). This file is the whole
# ENCODING side — the opcode grouping AND the funct / rt / sa rule that picks
# each UopSeq out of its group. What an instruction DOES is uop.py's business.
#
# The Mop/UopSeq nesting mirrors the manual's own decode shape: the Mop
# matches the opcode, and where an opcode is a whole family (SPECIAL, REGIMM,
# SPECIAL2, SPECIAL3) each UopSeq states the finer rule:
#   SPECIAL   funct — and funct|rs for srl/rotr, funct|sa for srlv/rotrv
#   REGIMM    the rt field is the sub-opcode
#   SPECIAL2  funct
#   SPECIAL3  funct — and funct|sa for seb/seh under bshfl
# srl and srlv MUST state the union too: a funct-only rule would claim the
# rotate as well (test_mips_decode_templates pins the exclusivity).
#
# Every UopSeq holds one µop, because MIPS32 cracks nothing. Exhaustive over
# uop.UOPS: every template appears in exactly one UopSeq (test_mips.py).
#
# NOT here: lwl/lwr/swl/swr (34, 38, 42, 46), the likely branches (20..23 and
# REGIMM 2/3), traps (SPECIAL 48..54, REGIMM 8..14), syscall/break (SPECIAL
# 12/13), sync (15), ll/sc (48/56), cache/pref (47/51), COP0/COP1 (16/17),
# madd/maddu/msub/msubu (SPECIAL2 0/1/4/5) — a word of any of these decodes
# into nothing, which the build's verify step reports.

from __future__ import annotations

from typing import Optional

from ..field_match import InstrFieldMatch
from ..mop import Mop, UopSeq
from ..uop import Uop
from . import field_match as FM
from . import uop as U


def _uop_when(
    uop           : Uop,
    matcher_field : Optional[InstrFieldMatch] = None,
    *values       : int,
) -> UopSeq:
    """The one-µop UopSeq a sub-field rule picks out of its opcode group.

    - no field, no values: the opcode alone identifies it
    """
    return UopSeq(uops          = (uop,),
                  matcher_field = matcher_field,
                  matcher_value = FM.val(*values) if values else None)


def _opcode_is_uop(opcode: int, uop: Uop) -> Mop:
    """A Mop for an opcode that is one instruction."""
    return Mop(matcher_field = FM.OPCODE,
               matcher_value = FM.val(opcode),
               uop_seq       = (_uop_when(uop),))


# opcode 000000 — SPECIAL, R-type: funct picks the instruction
MOP_SPECIAL = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b000000), uop_seq=(
    _uop_when(U.UOP_SLL,   FM.FUNCT,     0,   ),
    _uop_when(U.UOP_SRL,   FM.FUNCT_RS,  2, 0,),   # rs field 0
    _uop_when(U.UOP_ROTR,  FM.FUNCT_RS,  2, 1,),   # rs field 1: the rotate
    _uop_when(U.UOP_SRA,   FM.FUNCT,     3,   ),
    _uop_when(U.UOP_SLLV,  FM.FUNCT,     4,   ),
    _uop_when(U.UOP_SRLV,  FM.FUNCT_SA,  6, 0,),   # sa field 0
    _uop_when(U.UOP_ROTRV, FM.FUNCT_SA,  6, 1,),   # sa field 1: the rotate
    _uop_when(U.UOP_SRAV,  FM.FUNCT,     7,   ),
    _uop_when(U.UOP_JR,    FM.FUNCT,     8,   ),
    _uop_when(U.UOP_JALR,  FM.FUNCT,     9,   ),
    _uop_when(U.UOP_MOVZ,  FM.FUNCT,    10,   ),
    _uop_when(U.UOP_MOVN,  FM.FUNCT,    11,   ),
    _uop_when(U.UOP_MFHI,  FM.FUNCT,    16,   ),
    _uop_when(U.UOP_MTHI,  FM.FUNCT,    17,   ),
    _uop_when(U.UOP_MFLO,  FM.FUNCT,    18,   ),
    _uop_when(U.UOP_MTLO,  FM.FUNCT,    19,   ),
    _uop_when(U.UOP_MULT,  FM.FUNCT,    24,   ),
    _uop_when(U.UOP_MULTU, FM.FUNCT,    25,   ),
    _uop_when(U.UOP_DIV,   FM.FUNCT,    26,   ),
    _uop_when(U.UOP_DIVU,  FM.FUNCT,    27,   ),
    _uop_when(U.UOP_ADD,   FM.FUNCT,    32,   ),
    _uop_when(U.UOP_ADDU,  FM.FUNCT,    33,   ),
    _uop_when(U.UOP_SUB,   FM.FUNCT,    34,   ),
    _uop_when(U.UOP_SUBU,  FM.FUNCT,    35,   ),
    _uop_when(U.UOP_AND,   FM.FUNCT,    36,   ),
    _uop_when(U.UOP_OR,    FM.FUNCT,    37,   ),
    _uop_when(U.UOP_XOR,   FM.FUNCT,    38,   ),
    _uop_when(U.UOP_NOR,   FM.FUNCT,    39,   ),
    _uop_when(U.UOP_SLT,   FM.FUNCT,    42,   ),
    _uop_when(U.UOP_SLTU,  FM.FUNCT,    43,   ),
))

# opcode 000001 — REGIMM: the rt field is the sub-opcode
MOP_REGIMM = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b000001), uop_seq=(
    _uop_when(U.UOP_BLTZ,   FM.RT,  0,),
    _uop_when(U.UOP_BGEZ,   FM.RT,  1,),
    _uop_when(U.UOP_BLTZAL, FM.RT, 16,),
    _uop_when(U.UOP_BGEZAL, FM.RT, 17,),
))

# opcode 011100 — SPECIAL2: funct picks the instruction
MOP_SPECIAL2 = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b011100), uop_seq=(
    _uop_when(U.UOP_MUL, FM.FUNCT,  2,),
    _uop_when(U.UOP_CLZ, FM.FUNCT, 32,),
    _uop_when(U.UOP_CLO, FM.FUNCT, 33,),
))

# opcode 011111 — SPECIAL3: ext/ins by funct, seb/seh under bshfl by sa
MOP_SPECIAL3 = Mop(matcher_field=FM.OPCODE, matcher_value=FM.val(0b011111), uop_seq=(
    _uop_when(U.UOP_EXT, FM.FUNCT,     0,    ),
    _uop_when(U.UOP_INS, FM.FUNCT,     4,    ),
    _uop_when(U.UOP_SEB, FM.FUNCT_SA, 32, 16,),
    _uop_when(U.UOP_SEH, FM.FUNCT_SA, 32, 24,),
))

# --- the opcodes that are one instruction each ---------------------------------
MOP_J     = _opcode_is_uop(0b000010, U.UOP_J    )
MOP_JAL   = _opcode_is_uop(0b000011, U.UOP_JAL  )
MOP_BEQ   = _opcode_is_uop(0b000100, U.UOP_BEQ  )
MOP_BNE   = _opcode_is_uop(0b000101, U.UOP_BNE  )
MOP_BLEZ  = _opcode_is_uop(0b000110, U.UOP_BLEZ )
MOP_BGTZ  = _opcode_is_uop(0b000111, U.UOP_BGTZ )
MOP_ADDI  = _opcode_is_uop(0b001000, U.UOP_ADDI )
MOP_ADDIU = _opcode_is_uop(0b001001, U.UOP_ADDIU)
MOP_SLTI  = _opcode_is_uop(0b001010, U.UOP_SLTI )
MOP_SLTIU = _opcode_is_uop(0b001011, U.UOP_SLTIU)
MOP_ANDI  = _opcode_is_uop(0b001100, U.UOP_ANDI )
MOP_ORI   = _opcode_is_uop(0b001101, U.UOP_ORI  )
MOP_XORI  = _opcode_is_uop(0b001110, U.UOP_XORI )
MOP_LUI   = _opcode_is_uop(0b001111, U.UOP_LUI  )
MOP_LB    = _opcode_is_uop(0b100000, U.UOP_LB   )
MOP_LH    = _opcode_is_uop(0b100001, U.UOP_LH   )
MOP_LW    = _opcode_is_uop(0b100011, U.UOP_LW   )
MOP_LBU   = _opcode_is_uop(0b100100, U.UOP_LBU  )
MOP_LHU   = _opcode_is_uop(0b100101, U.UOP_LHU  )
MOP_SB    = _opcode_is_uop(0b101000, U.UOP_SB   )
MOP_SH    = _opcode_is_uop(0b101001, U.UOP_SH   )
MOP_SW    = _opcode_is_uop(0b101011, U.UOP_SW   )

# Every instruction group, as Mops over the µop templates of uop.py.
MOP_TABLE = (MOP_SPECIAL, MOP_REGIMM, MOP_SPECIAL2, MOP_SPECIAL3,
             MOP_J      , MOP_JAL   , MOP_BEQ     , MOP_BNE     , MOP_BLEZ, MOP_BGTZ,
             MOP_ADDI   , MOP_ADDIU , MOP_SLTI    , MOP_SLTIU   ,
             MOP_ANDI   , MOP_ORI   , MOP_XORI    , MOP_LUI     ,
             MOP_LB     , MOP_LH    , MOP_LW      , MOP_LBU     , MOP_LHU , MOP_SB  , MOP_SH, MOP_SW)
