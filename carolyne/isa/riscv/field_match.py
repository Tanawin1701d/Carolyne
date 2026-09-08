# Where RV32I's encoding fields are in the 32-bit instruction word
# (uop_contract.md §1.3). Segments are (start, end) with end EXCLUSIVE and
# bit 0 = LSB, so funct7 = (25, 32) is bits 31..25.
#
# RV32I is fixed 32-bit, so ILEN_BYTES is the constant 4 and no length decoder
# is needed; PC_WIDTH / PC_ALIGN are beside it as one addressing group.
#
# The scrambled immediates (S/B/J) are why InstrFieldMatch takes a TUPLE of
# segments. imm_b keeps four segments even where two are next to each other —
# (7,8) is imm[11] and (8,12) is imm[4:1], and merging them would hide that
# they go to different places in the value.
#
# The six base FORMATS are InstrFieldMatch unions of the fields they contain,
# DECLARED but NOT USED: Mop has no format slot, so rv32i.py names the format
# of each opcode group in a comment. The mop table is grouped by OPCODE, not by
# format, because one I-type Mop would have to cover four opcodes (LOAD,
# OP-IMM, JALR, SYSTEM), which one matcher cannot state.
#
# `val(...)` is the package's shorthand for an InstrValueMatch, kept here
# beside the fields those values are compared against.
#
# NOT here: how the matched bits become a VALUE. A rule here says WHICH BITS,
# never where a segment goes in the assembled immediate or whether it is
# signed. That is stated per operand by `imm_extract` (imm.py).

from __future__ import annotations

from ..field_match import InstrFieldMatch, InstrValueMatch
from .reg import X_LEN


def val(*values: int) -> InstrValueMatch:
    """One match value per segment, in the field's own segment order."""
    return InstrValueMatch(values)

# --- instruction addressing (the three scalars IsaBase takes) ---------------
# Grouped here because they are one subject with the field positions below:
# where an instruction is and how long it is. PC_WIDTH is XLEN by the RV32I
# spec — the PC still has a width even though it is not a register class, and
# reg.py says why it is not one.
PC_WIDTH   = X_LEN      # program counter is XLEN bits
PC_ALIGN   = 4          # instruction addresses are 4-byte aligned (2 with the C ext)
ILEN_BYTES = 4          # RV32I is fixed-length; no length decoder needed
DLEN_BYTES = 4          # widest data access: LW/SW move a 32-bit word

# --- register / function fields --------------------------------------------
OPCODE = InstrFieldMatch("opcode", ((0, 7),))
RD     = InstrFieldMatch("rd",     ((7, 12),))
FUNCT3 = InstrFieldMatch("funct3", ((12, 15),))
RS1    = InstrFieldMatch("rs1",    ((15, 20),))
RS2    = InstrFieldMatch("rs2",    ((20, 25),))
FUNCT7 = InstrFieldMatch("funct7", ((25, 32),))

# add vs sub, srl vs sra and the shift-immediates share a funct3 and differ
# only in funct7, so selecting one needs both fields at once.
FUNCT3_7 = FUNCT3 | FUNCT7
# --- immediates, one per instruction format --------------------------------
IMM_I = InstrFieldMatch("imm_i", ((20, 32),))                       # imm[11:0]
IMM_S = InstrFieldMatch("imm_s", ((7, 12), (25, 32)))               # imm[4:0], imm[11:5]
IMM_B = InstrFieldMatch("imm_b", ((7, 8), (8, 12),                  # imm[11], imm[4:1]
                                  (25, 31), (31, 32)))              # imm[10:5], imm[12]
IMM_U = InstrFieldMatch("imm_u", ((12, 32),))                       # imm[31:12]
IMM_J = InstrFieldMatch("imm_j", ((12, 20), (20, 21),               # imm[19:12], imm[11]
                                  (21, 31), (31, 32)))              # imm[10:1], imm[20]
SHAMT = InstrFieldMatch("shamt", ((20, 25),))                       # slli/srli/srai

# --- the six base instruction formats ---------------------------------------
# One rule per row of the format figure (spec ch. 2.2): the union of the fields
# that format is built from, so a format is stated in the same type as a field.
# Fields are unioned in ASCENDING first-bit order — opcode leads, reading the
# figure right to left — which makes each format's segments tile the 32-bit word
# exactly once (pinned in test_riscv.py). A field's OWN segment order is its own
# statement and is left alone: imm_s contributes (7,12) then (25,32), so S_TYPE's
# segment list is not globally ascending, and must not be sorted into being.
R_TYPE = OPCODE.union(RD, FUNCT3, RS1, RS2, FUNCT7, name="r_type")  # funct7 rs2 rs1 funct3 rd opcode
I_TYPE = OPCODE.union(RD, FUNCT3, RS1, IMM_I,       name="i_type")  # imm[11:0] rs1 funct3 rd opcode
S_TYPE = OPCODE.union(IMM_S, FUNCT3, RS1, RS2,      name="s_type")  # imm[11:5] rs2 rs1 funct3 imm[4:0] opcode
B_TYPE = OPCODE.union(IMM_B, FUNCT3, RS1, RS2,      name="b_type")  # imm[12|10:5] rs2 rs1 funct3 imm[4:1|11] opcode
U_TYPE = OPCODE.union(RD, IMM_U,                    name="u_type")  # imm[31:12] rd opcode
J_TYPE = OPCODE.union(RD, IMM_J,                    name="j_type")  # imm[20|10:1|11|19:12] rd opcode

FORMATS = (R_TYPE, I_TYPE, S_TYPE, B_TYPE, U_TYPE, J_TYPE)

# slli/srli/srai are NOT a seventh format: they are I-type encodings whose
# imm[11:0] is read as funct7|shamt, which is why their templates match on
# FUNCT3_7 and take SHAMT rather than IMM_I (uop.py).
