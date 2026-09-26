# One Uop template per MIPS32r2 user-mode integer instruction, transcribed
# from the MIPS32 instruction set manual (volume II).
#
# EVERY INSTRUCTION IS EXACTLY ONE µop: addressing is base+offset, a jump
# writes its own link register, and MULT/DIV write HI and LO as one µop's two
# destinations — nothing cracks and this ISA uses no µtemp.
#
# Module constants named UOP_<mnemonic>, one per instruction; each template
# NAMES ITSELF and DECLARES ITS ID (`uop_idx`), 0..62. The ids are grouped by
# the unit that runs them — alu, mem, control, muldiv — so a unit's ids are
# one contiguous run and ExecUnitBase.uop_idx_ranges() costs one compare.
#
# A template carries NO MATCHER; the funct/rt rules are on the UopSeqs in
# mop.py beside the opcode they refine.
#
# Every branch and jump carries the feature "delay_slot": the instruction
# after it executes whether or not the branch is taken. The engine does not
# read the feature yet, so the build holds every slot to a nop
# (compile_tool verify.py); the feature is what will let the engine retire
# the slot before it redirects.
#
# LIMIT: add / addi / sub do not trap on overflow — there is no trap policy —
# so they compute what addu / addiu / subu compute.
# NOT here: lwl/lwr/swl/swr, the likely branches, traps, syscall/break, sync,
# ll/sc, cache/pref, CP0, the FPU, and madd/maddu/msub/msubu (four sources:
# rs, rt, hi and lo; the compiler is told -mno-imadd).

from __future__ import annotations

from ..uop import Uop
from .operand import (OPR_BITFIELD_EXT, OPR_BITFIELD_INS, OPR_HI_DEST, OPR_HI_SRC ,
                      OPR_IMM_BR      , OPR_IMM_J       , OPR_IMM_LUI, OPR_IMM_S16, OPR_IMM_S16_ST,
                      OPR_IMM_Z16     , OPR_LO_DEST     , OPR_LO_SRC , OPR_RA     , OPR_RD        , OPR_RD_SRC3,
                      OPR_RS          , OPR_RS_SRC2     , OPR_RT     , OPR_RT_DEST, OPR_RT_SRC1   , OPR_SA     )

_RD     = (OPR_RD     ,                             )
_RT_D   = (OPR_RT_DEST,                             )
_REG    = (OPR_RS     , OPR_RT     ,                )   # rd = rs op rt
_MOV    = (OPR_RS     , OPR_RT     , OPR_RD_SRC3   ,)   # movz/movn: rd = test(rt) ? rs : rd
_SHIFT  = (OPR_RT_SRC1, OPR_SA     ,                )   # rd = rt shift sa
_SHIFTV = (OPR_RT_SRC1, OPR_RS_SRC2,                )   # rd = rt shift rs[4:0]
_RT1    = (OPR_RT_SRC1,                             )   # seb/seh: rd = extend(rt)
_RS1    = (OPR_RS     ,                             )   # clz/clo, jr, mthi/mtlo, the one-register branches
_IMM_S  = (OPR_RS     , OPR_IMM_S16,                )   # rt = rs op sext(imm16)
_IMM_Z  = (OPR_RS     , OPR_IMM_Z16,                )   # rt = rs op zext(imm16)
_ADDR   = (OPR_RS     , OPR_IMM_S16,                )   # load:  base + offset
_STORE  = (OPR_RS     , OPR_RT     , OPR_IMM_S16_ST,)   # store: base + data + offset
_BR2    = (OPR_RS     , OPR_RT     , OPR_IMM_BR    ,)   # beq/bne
_BR1    = (OPR_RS     , OPR_IMM_BR ,                )   # blez/bgtz/bltz/bgez and the link forms
_HILO   = (OPR_HI_DEST, OPR_LO_DEST,                )

# What a µop IS to the machine, beyond its operands (uop_contract: the ISA
# states the fact, the generator builds the hardware).
_FEAT_BRANCH = ("is_branch", "delay_slot")   # augments the pc, after the slot
_FEAT_STORE  = ("is_store",)                 # written to memory only on retirement

# --- alu, ids 0..33 ------------------------------------------------------------
UOP_ADD   = Uop("ADD"  ,  0, srcs=_REG          , dests=_RD  ,)
UOP_ADDU  = Uop("ADDU" ,  1, srcs=_REG          , dests=_RD  ,)
UOP_SUB   = Uop("SUB"  ,  2, srcs=_REG          , dests=_RD  ,)
UOP_SUBU  = Uop("SUBU" ,  3, srcs=_REG          , dests=_RD  ,)
UOP_AND   = Uop("AND"  ,  4, srcs=_REG          , dests=_RD  ,)
UOP_OR    = Uop("OR"   ,  5, srcs=_REG          , dests=_RD  ,)
UOP_XOR   = Uop("XOR"  ,  6, srcs=_REG          , dests=_RD  ,)
UOP_NOR   = Uop("NOR"  ,  7, srcs=_REG          , dests=_RD  ,)
UOP_SLT   = Uop("SLT"  ,  8, srcs=_REG          , dests=_RD  ,)
UOP_SLTU  = Uop("SLTU" ,  9, srcs=_REG          , dests=_RD  ,)

UOP_ADDI  = Uop("ADDI" , 10, srcs=_IMM_S        , dests=_RT_D,)
UOP_ADDIU = Uop("ADDIU", 11, srcs=_IMM_S        , dests=_RT_D,)
UOP_SLTI  = Uop("SLTI" , 12, srcs=_IMM_S        , dests=_RT_D,)
UOP_SLTIU = Uop("SLTIU", 13, srcs=_IMM_S        , dests=_RT_D,)   # unsigned compare against the SIGN-extended imm

UOP_ANDI  = Uop("ANDI" , 14, srcs=_IMM_Z        , dests=_RT_D,)
UOP_ORI   = Uop("ORI"  , 15, srcs=_IMM_Z        , dests=_RT_D,)
UOP_XORI  = Uop("XORI" , 16, srcs=_IMM_Z        , dests=_RT_D,)

UOP_LUI   = Uop("LUI"  , 17, srcs=(OPR_IMM_LUI,), dests=_RT_D,)

UOP_SLL   = Uop("SLL"  , 18, srcs=_SHIFT        , dests=_RD  ,)   # sll $0,$0,0 is nop
UOP_SRL   = Uop("SRL"  , 19, srcs=_SHIFT        , dests=_RD  ,)
UOP_SRA   = Uop("SRA"  , 20, srcs=_SHIFT        , dests=_RD  ,)
UOP_ROTR  = Uop("ROTR" , 21, srcs=_SHIFT        , dests=_RD  ,)

UOP_SLLV  = Uop("SLLV" , 22, srcs=_SHIFTV       , dests=_RD  ,)
UOP_SRLV  = Uop("SRLV" , 23, srcs=_SHIFTV       , dests=_RD  ,)
UOP_SRAV  = Uop("SRAV" , 24, srcs=_SHIFTV       , dests=_RD  ,)
UOP_ROTRV = Uop("ROTRV", 25, srcs=_SHIFTV       , dests=_RD  ,)

UOP_MOVZ  = Uop("MOVZ" , 26, srcs=_MOV          , dests=_RD  ,)
UOP_MOVN  = Uop("MOVN" , 27, srcs=_MOV          , dests=_RD  ,)

UOP_CLZ   = Uop("CLZ"  , 28, srcs=_RS1          , dests=_RD  ,)
UOP_CLO   = Uop("CLO"  , 29, srcs=_RS1          , dests=_RD  ,)
UOP_SEB   = Uop("SEB"  , 30, srcs=_RT1          , dests=_RD  ,)
UOP_SEH   = Uop("SEH"  , 31, srcs=_RT1          , dests=_RD  ,)

UOP_EXT   = Uop("EXT"  , 32, srcs=(OPR_RS, OPR_BITFIELD_EXT)        , dests=_RT_D,)
UOP_INS   = Uop("INS"  , 33, srcs=(OPR_RS, OPR_RT, OPR_BITFIELD_INS), dests=_RT_D,)   # rt is read and written

ALUS = (UOP_ADD , UOP_ADDU , UOP_SUB , UOP_SUBU , UOP_AND , UOP_OR  , UOP_XOR , UOP_NOR  ,
        UOP_SLT , UOP_SLTU ,
        UOP_ADDI, UOP_ADDIU, UOP_SLTI, UOP_SLTIU, UOP_ANDI, UOP_ORI , UOP_XORI, UOP_LUI  ,
        UOP_SLL , UOP_SRL  , UOP_SRA , UOP_ROTR , UOP_SLLV, UOP_SRLV, UOP_SRAV, UOP_ROTRV,
        UOP_MOVZ, UOP_MOVN , UOP_CLZ , UOP_CLO  , UOP_SEB , UOP_SEH , UOP_EXT , UOP_INS  )

# --- mem, ids 34..41: rt = mem[rs + offset] / mem[rs + offset] = rt ----------
UOP_LB  = Uop("LB" , 34, srcs=_ADDR , dests=_RT_D,                               )
UOP_LH  = Uop("LH" , 35, srcs=_ADDR , dests=_RT_D,                               )
UOP_LW  = Uop("LW" , 36, srcs=_ADDR , dests=_RT_D,                               )
UOP_LBU = Uop("LBU", 37, srcs=_ADDR , dests=_RT_D,                               )
UOP_LHU = Uop("LHU", 38, srcs=_ADDR , dests=_RT_D,                               )
UOP_SB  = Uop("SB" , 39, srcs=_STORE,              specified_feature=_FEAT_STORE,)
UOP_SH  = Uop("SH" , 40, srcs=_STORE,              specified_feature=_FEAT_STORE,)
UOP_SW  = Uop("SW" , 41, srcs=_STORE,              specified_feature=_FEAT_STORE,)

LOADS  = (UOP_LB, UOP_LH, UOP_LW, UOP_LBU, UOP_LHU)
STORES = (UOP_SB, UOP_SH, UOP_SW)

# --- control, ids 42..53: redirect after the delay slot -----------------------
UOP_BEQ    = Uop("BEQ"   , 42, srcs=_BR2        ,                  specified_feature=_FEAT_BRANCH,)
UOP_BNE    = Uop("BNE"   , 43, srcs=_BR2        ,                  specified_feature=_FEAT_BRANCH,)
UOP_BLEZ   = Uop("BLEZ"  , 44, srcs=_BR1        ,                  specified_feature=_FEAT_BRANCH,)
UOP_BGTZ   = Uop("BGTZ"  , 45, srcs=_BR1        ,                  specified_feature=_FEAT_BRANCH,)
UOP_BLTZ   = Uop("BLTZ"  , 46, srcs=_BR1        ,                  specified_feature=_FEAT_BRANCH,)
UOP_BGEZ   = Uop("BGEZ"  , 47, srcs=_BR1        ,                  specified_feature=_FEAT_BRANCH,)
UOP_BLTZAL = Uop("BLTZAL", 48, srcs=_BR1        , dests=(OPR_RA,), specified_feature=_FEAT_BRANCH,)
UOP_BGEZAL = Uop("BGEZAL", 49, srcs=_BR1        , dests=(OPR_RA,), specified_feature=_FEAT_BRANCH,)
UOP_J      = Uop("J"     , 50, srcs=(OPR_IMM_J,),                  specified_feature=_FEAT_BRANCH,)
UOP_JAL    = Uop("JAL"   , 51, srcs=(OPR_IMM_J,), dests=(OPR_RA,), specified_feature=_FEAT_BRANCH,)
UOP_JR     = Uop("JR"    , 52, srcs=_RS1        ,                  specified_feature=_FEAT_BRANCH,)
UOP_JALR   = Uop("JALR"  , 53, srcs=_RS1        , dests=_RD      , specified_feature=_FEAT_BRANCH,)

BRANCHES = (UOP_BEQ   , UOP_BNE   , UOP_BLEZ, UOP_BGTZ, UOP_BLTZ, UOP_BGEZ, UOP_BLTZAL, UOP_BGEZAL)
JUMPS    = (UOP_J     , UOP_JAL   , UOP_JR  , UOP_JALR)
LINKS    = (UOP_BLTZAL, UOP_BGEZAL, UOP_JAL , UOP_JALR)   # write the return address
CONTROL  = BRANCHES + JUMPS

# --- muldiv, ids 54..62: the HI/LO accumulator ---------------------------------
UOP_MULT  = Uop("MULT" , 54, srcs=_REG         , dests=_HILO         ,)
UOP_MULTU = Uop("MULTU", 55, srcs=_REG         , dests=_HILO         ,)
UOP_DIV   = Uop("DIV"  , 56, srcs=_REG         , dests=_HILO         ,)   # lo = quotient, hi = remainder
UOP_DIVU  = Uop("DIVU" , 57, srcs=_REG         , dests=_HILO         ,)
UOP_MUL   = Uop("MUL"  , 58, srcs=_REG         , dests=_RD           ,)   # the low word to rd; hi/lo untouched
UOP_MFHI  = Uop("MFHI" , 59, srcs=(OPR_HI_SRC,), dests=_RD           ,)
UOP_MFLO  = Uop("MFLO" , 60, srcs=(OPR_LO_SRC,), dests=_RD           ,)
UOP_MTHI  = Uop("MTHI" , 61, srcs=_RS1         , dests=(OPR_HI_DEST,),)
UOP_MTLO  = Uop("MTLO" , 62, srcs=_RS1         , dests=(OPR_LO_DEST,),)

HILO_WRITERS = (UOP_MULT, UOP_MULTU, UOP_DIV , UOP_DIVU)   # write BOTH halves
MULDIVS      = (UOP_MULT, UOP_MULTU, UOP_DIV , UOP_DIVU, UOP_MUL,
                UOP_MFHI, UOP_MFLO , UOP_MTHI, UOP_MTLO)

UOPS = ALUS + LOADS + STORES + CONTROL + MULDIVS
