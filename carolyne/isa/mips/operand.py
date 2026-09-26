# Every operand rule MIPS32 instructions use — the register slots and the
# immediates. Each is a *rule*, never a value: "this index, or this constant,
# comes from that encoding field at runtime" (uop_contract.md §1.1, §2).
#
# Module CONSTANTS, shared by every shape, built on eight shared AtomicOperand
# cores that target reg.R / reg.HI / reg.LO — the class instances this
# description declares, matched by IsaBase by identity.
#
# The cores are named per SLOT: src 1 / src 2 / src 3 and dest 1 on the
# general registers, src_hi / src_lo / dest_hi / dest_lo on the accumulator
# halves. Unlike RV32I, one SLOT reads several FIELDS: a shift's value is rt
# (OPR_RT_SRC1) where an add's is rs (OPR_RS), and movz/movn read the old rd
# as a third source. Each (core, field) pair is its own rule, and the body
# reads the slot without knowing which field filled it.
#
# The FieldRef name of a register operand is taken FROM the field-match table
# rather than written again, so the two halves agree by construction.
#
# An immediate operand targets `reg.IMM_TARGET` and carries NO index. The
# accumulator operands carry no index either: a one-register class has
# nothing to choose. OPR_RA is the implicit $31 the link instructions write.

from __future__ import annotations

from ..atomic_operand import AtomicOperand, OperandRole, TargetKind
from ..operand import FieldRef, Operand
from . import field_match as FM
from . import imm as IMM_RULE
from .reg import GPR_FILE, HI_FILE, IMM_TARGET, LO_FILE

SRC, DEST = OperandRole.SRC, OperandRole.DEST
ARCH, IMM = TargetKind.ARCH, TargetKind.IMM

# src 2 and src 3 both offer a register AND an immediate: the same slot holds
# rt for an add, the immediate for an addi, the old rd for a movz.
AOPR_SRC_1   = AtomicOperand(SRC, "src_1" , reg_file=GPR_FILE)
AOPR_SRC_2   = AtomicOperand(SRC, "src_2" , reg_file=GPR_FILE, intermediate=IMM_TARGET)
AOPR_SRC_3   = AtomicOperand(SRC, "src_3" , reg_file=GPR_FILE, intermediate=IMM_TARGET)
AOPR_SRC_HI  = AtomicOperand(SRC, "src_hi", reg_file=HI_FILE )
AOPR_SRC_LO  = AtomicOperand(SRC, "src_lo", reg_file=LO_FILE )

AOPR_DEST_1  = AtomicOperand(DEST, "dest_1" , reg_file=GPR_FILE)
AOPR_DEST_HI = AtomicOperand(DEST, "dest_hi", reg_file=HI_FILE )
AOPR_DEST_LO = AtomicOperand(DEST, "dest_lo", reg_file=LO_FILE )

ATOMIC_OPERANDS = (AOPR_SRC_1 , AOPR_SRC_2  , AOPR_SRC_3  , AOPR_SRC_HI, AOPR_SRC_LO,
                   AOPR_DEST_1, AOPR_DEST_HI, AOPR_DEST_LO)


# --- register operands ------------------------------------------------------
OPR_RS      = Operand(AOPR_SRC_1  , ARCH, FieldRef(FM.RS.name), matcher=FM.RS)   # src 1: rs
OPR_RT_SRC1 = Operand(AOPR_SRC_1  , ARCH, FieldRef(FM.RT.name), matcher=FM.RT)   # src 1: rt, a shift's value
OPR_RT      = Operand(AOPR_SRC_2  , ARCH, FieldRef(FM.RT.name), matcher=FM.RT)   # src 2: rt
OPR_RS_SRC2 = Operand(AOPR_SRC_2  , ARCH, FieldRef(FM.RS.name), matcher=FM.RS)   # src 2: rs, a variable shift's count
OPR_RD_SRC3 = Operand(AOPR_SRC_3  , ARCH, FieldRef(FM.RD.name), matcher=FM.RD)   # src 3: rd, the value movz/movn keep
OPR_HI_SRC  = Operand(AOPR_SRC_HI , ARCH)                                        # one register: no index
OPR_LO_SRC  = Operand(AOPR_SRC_LO , ARCH)

OPR_RD      = Operand(AOPR_DEST_1 , ARCH, FieldRef(FM.RD.name), matcher=FM.RD)   # dest: rd
OPR_RT_DEST = Operand(AOPR_DEST_1 , ARCH, FieldRef(FM.RT.name), matcher=FM.RT)   # dest: rt (I-type, loads)
OPR_RA      = Operand(AOPR_DEST_1 , ARCH, 31)                                    # dest: $31, the link instructions
OPR_HI_DEST = Operand(AOPR_DEST_HI, ARCH)
OPR_LO_DEST = Operand(AOPR_DEST_LO, ARCH)

OPR_REGS = (OPR_RS, OPR_RT_SRC1, OPR_RT, OPR_RS_SRC2, OPR_RD_SRC3, OPR_HI_SRC, OPR_LO_SRC,
            OPR_RD, OPR_RT_DEST, OPR_RA, OPR_HI_DEST, OPR_LO_DEST)

# --- immediate operands -----------------------------------------------------
# No index: an immediate is not a register of a class. The matcher says
# which bits carry the value; `imm_extract` (imm.py) what they mean. The
# zero-extended ones state no rule: one contiguous field is the default.
OPR_IMM_S16      = Operand(AOPR_SRC_2, IMM, matcher=FM.IMM16,    imm_extract=IMM_RULE.imm_s16)      # addi/slti/loads
OPR_IMM_Z16      = Operand(AOPR_SRC_2, IMM, matcher=FM.IMM16)                                       # andi/ori/xori
OPR_IMM_LUI      = Operand(AOPR_SRC_2, IMM, matcher=FM.IMM16,    imm_extract=IMM_RULE.imm_lui)      # lui
OPR_SA           = Operand(AOPR_SRC_2, IMM, matcher=FM.SA)                                          # sll/srl/sra/rotr: 5-bit count
OPR_BITFIELD_EXT = Operand(AOPR_SRC_2, IMM, matcher=FM.BITFIELD, imm_extract=IMM_RULE.imm_bitfield) # ext: pos, size-1

OPR_IMM_S16_ST   = Operand(AOPR_SRC_3, IMM, matcher=FM.IMM16      , imm_extract=IMM_RULE.imm_s16)      # stores: data is src 2
OPR_IMM_BR       = Operand(AOPR_SRC_3, IMM, matcher=FM.IMM16      , imm_extract=IMM_RULE.imm_br)       # branches: offset << 2
OPR_IMM_J        = Operand(AOPR_SRC_3, IMM, matcher=FM.INSTR_INDEX, imm_extract=IMM_RULE.imm_j)        # j/jal: index << 2
OPR_BITFIELD_INS = Operand(AOPR_SRC_3, IMM, matcher=FM.BITFIELD   , imm_extract=IMM_RULE.imm_bitfield) # ins: lsb, msb

OPR_IMMS = (OPR_IMM_S16   , OPR_IMM_Z16, OPR_IMM_LUI, OPR_SA          , OPR_BITFIELD_EXT,
            OPR_IMM_S16_ST, OPR_IMM_BR , OPR_IMM_J  , OPR_BITFIELD_INS)
