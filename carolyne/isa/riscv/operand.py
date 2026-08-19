# Every operand rule RV32I instructions draw from — the three register slots
# (rd, rs1, rs2) and the six immediates. Each is a *rule*, never a value:
# "this index / this constant arrives from that encoding field at runtime"
# (uop_contract.md §1.1, §2).
#
# Module CONSTANTS, shared by every shape, built on four shared AtomicOperand
# cores. The register rules target reg.RegFile, the one class instance this
# description declares — IsaBase matches reg files by identity, so the operand
# constants and the declared class must be the same object.
#
# The FieldRef name of a register operand is taken FROM the field-match table
# (`FM.RD.name`) rather than spelled again, so the two halves agree by
# construction, and `matcher` carries that field's bit positions alongside the
# index rule.
#
# The cores are named per SLOT (src 1 = rs1, src 2 = rs2, src 3 = the
# immediate, dest 1 = rd); AOPR_SRC_1 and AOPR_SRC_2 are value-equal twins on
# purpose. Each rule states its role and its target_kind. RV32I reads rs1/rs2
# and writes rd through three DIFFERENT encoding fields, so no slot is ever
# both and one OPR_RD serves all 30 instructions that write a register.
#
# An immediate operand targets `reg.ImmTarget` and carries NO index: an index
# answers "which register of the class", which an immediate has not got. The
# six immediate constants differ only by their matcher. No µtemp operands
# beyond that — RV32I produces no intra-instruction values.
#
# KNOWN GAPS
# - An immediate operand cannot say how its bits become a value: sign
#   extension (imm_i/s/b/j are signed, shamt is not), the implicit low zero
#   of b/j-type, and u-type landing in bits 31:12 are all unstateable. Nor
#   can InstrFieldMatch say where each segment of a scrambled immediate lands
#   (field_match.py's gap): imm_s's (7,12) is imm[4:0] and (25,32) is
#   imm[11:5]. An extractor cannot be generated from this alone.
# - These constants are declared but not yet USED by any µop shape: Uop has
#   no `imm` field while the matcher design is in flight, and contract §2
#   keeps immediates out of the src slots. rv32i.py marks each site `# imm:`
#   with the constant that belongs there.

from __future__ import annotations

from .. import Intermediate
from ..atomic_operand import AtomicOperand, OperandRole, TargetKind
from ..operand import FieldRef, Operand
from . import field_match as FM
from .reg import ImmTarget, RegFile

SRC, DEST   = OperandRole.SRC, OperandRole.DEST
ARCH, TEMP  = TargetKind.ARCH, TargetKind.TEMP

# The cores the rules below build on — one per SLOT of an RV32I instruction,
# which is what the numbering says: src 1 is rs1, src 2 is rs2, src 3 is the
# immediate, and there is one destination. An AtomicOperand is frozen and
# value-equal, so sharing one couples nothing.
#
# Each core offers exactly ONE target, so every operand here selects ARCH or
# TEMP with nothing else on offer. The two-target form is for an ISA whose
# single encoding slot resolves either way (x86 ModRM r/m); RV32I has no such
# slot, and stating the selection anyway is what keeps a rule readable on its
# own.
AOPR_SRC_1   = AtomicOperand(SRC,  "src_1",  reg_file=RegFile)
AOPR_SRC_2   = AtomicOperand(SRC,  "src_2",  reg_file=RegFile, intermediate=ImmTarget)
AOPR_SRC_3   = AtomicOperand(SRC,  "src_3",  intermediate=ImmTarget)
AOPR_DEST_1  = AtomicOperand(DEST, "dest_1", reg_file=RegFile)


# --- register operands ------------------------------------------------------
OPR_RD  = Operand(AOPR_DEST_1, ARCH, FieldRef(FM.RD.name),  matcher=FM.RD)   # bits 11..7
OPR_RS1 = Operand(AOPR_SRC_1,  ARCH, FieldRef(FM.RS1.name), matcher=FM.RS1)  # src 1, addr base
OPR_RS2 = Operand(AOPR_SRC_2,  ARCH, FieldRef(FM.RS2.name), matcher=FM.RS2)  # src 2, store data

OPR_REGS = (OPR_RD, OPR_RS1, OPR_RS2)

# --- immediate operands -----------------------------------------------------
# No index: an immediate is not a register of a class. The matcher is the
# whole rule — which bits of the instruction word carry the value. All six
# select TEMP off the one immediate core.
OPR_IMM_I     = Operand(AOPR_SRC_2, TEMP, matcher=FM.IMM_I)     # addi/loads/jalr: 12-bit
OPR_IMM_S     = Operand(AOPR_SRC_3, TEMP, matcher=FM.IMM_S)     # stores: 12-bit, split field
OPR_IMM_B     = Operand(AOPR_SRC_3, TEMP, matcher=FM.IMM_B)     # branches: low bit implicit 0
OPR_IMM_U     = Operand(AOPR_SRC_2, TEMP, matcher=FM.IMM_U)     # lui/auipc: bits 31..12
OPR_IMM_J     = Operand(AOPR_SRC_2, TEMP, matcher=FM.IMM_J)     # jal: low bit implicit 0
OPR_IMM_SHAMT = Operand(AOPR_SRC_2, TEMP, matcher=FM.SHAMT)     # slli/srli/srai: 5-bit count

OPR_IMMS = (OPR_IMM_I, OPR_IMM_S, OPR_IMM_B, OPR_IMM_U, OPR_IMM_J, OPR_IMM_SHAMT)
