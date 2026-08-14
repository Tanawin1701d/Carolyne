# Every operand rule RV32I instructions draw from — the three register slots
# (rd, rs1, rs2) and the six immediates. Each is a *rule*, never a value:
# "this index / this constant arrives from that encoding field at runtime"
# (uop_contract.md §1.1, §2).
#
# Decisions (2026-08-14):
# - Module CONSTANTS, shared by every shape. The register ones target
#   regs.RegFile, the one class instance this description declares — IsaBase
#   matches reg files by identity, so an operand constant and the declared
#   class must be the same object (regs.py header). An Operand is frozen and
#   value-only, so sharing one across every instruction costs nothing and
#   reads better than rebuilding an identical slot per shape.
# - The FieldRef name of a register operand is taken FROM the field-match
#   table (`FM.RD.name`) rather than spelled again as a literal. The two
#   halves — "which encoding field supplies this index" and "which bits that
#   field occupies" — are independent types, so a typo in either would only
#   surface when a decoder is generated. Deriving one from the other makes
#   them agree by construction.
# - `matcher` carries the field's bit positions alongside the index rule, so
#   an operand says both which field it reads and where that field lives.
#   That is the FieldRef→bits binding the layer above defers to "when a
#   cracker is bound to an encoding"; nothing checks it yet, but the
#   description can already state it.
# - An immediate operand targets `regs.ImmTarget` and carries NO index. An
#   index rule answers "which register of the class", which an immediate does
#   not have — the layer above enforces exactly that (Operand on an
#   Intermediate carries no index), so the six constants differ only by their
#   matcher, and the matcher is what says which bits the value comes from.
# - No µtemp operands beyond that: RV32I produces no intra-instruction values
#   (rv32i.py header). A real µtemp must be built where its instruction is
#   and never shared, so it could not be a constant here.
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

from ..operand import FieldRef, Operand
from . import field_match as FM
from .regs import ImmTarget, RegFile

# --- register operands ------------------------------------------------------
OPR_RD  = Operand(RegFile, FieldRef(FM.RD.name),  matcher=FM.RD)    # dest, bits 11..7
OPR_RS1 = Operand(RegFile, FieldRef(FM.RS1.name), matcher=FM.RS1)   # src 1, address base
OPR_RS2 = Operand(RegFile, FieldRef(FM.RS2.name), matcher=FM.RS2)   # src 2, store data

OPR_REGS = (OPR_RD, OPR_RS1, OPR_RS2)

# --- immediate operands -----------------------------------------------------
# No index: an immediate is not a register of a class. The matcher is the
# whole rule — which bits of the instruction word carry the value.
OPR_IMM_I     = Operand(ImmTarget, matcher=FM.IMM_I)    # addi/loads/jalr: 12-bit
OPR_IMM_S     = Operand(ImmTarget, matcher=FM.IMM_S)    # stores: 12-bit, split field
OPR_IMM_B     = Operand(ImmTarget, matcher=FM.IMM_B)    # branches: low bit implicit 0
OPR_IMM_U     = Operand(ImmTarget, matcher=FM.IMM_U)    # lui/auipc: bits 31..12
OPR_IMM_J     = Operand(ImmTarget, matcher=FM.IMM_J)    # jal: low bit implicit 0
OPR_IMM_SHAMT = Operand(ImmTarget, matcher=FM.SHAMT)    # slli/srli/srai: 5-bit count

OPR_IMMS = (OPR_IMM_I, OPR_IMM_S, OPR_IMM_B, OPR_IMM_U, OPR_IMM_J, OPR_IMM_SHAMT)
