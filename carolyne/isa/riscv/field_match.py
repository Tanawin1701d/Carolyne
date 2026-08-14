# Where RV32I's encoding fields live in the 32-bit instruction word
# (uop_contract.md §1.3). Segments are (start, end) with end EXCLUSIVE and
# bit 0 = LSB, so funct7 = (25, 32) is bits 31..25.
#
# Decisions (2026-08-14):
# - RV32I is fixed 32-bit, so `ilen` is the constant 4 and no length decoder
#   is needed. The field has no type in the isa layer yet (§6 deliverable
#   three); ILEN_BYTES below is the value it will carry.
# - The scrambled immediates (S/B/J) are the reason InstrFieldMatch takes a
#   TUPLE of segments. imm_b is written as four segments rather than merged
#   ranges even where two are adjacent — (7,8) is imm[11] and (8,12) is
#   imm[4:1], and merging them would erase that they land in different places.
#
# KNOWN GAPS — this file is where the encoding side runs out of road, and the
# missing pieces belong in the contract, not here:
# - InstrFieldMatch carries no VALUE to match. "opcode == 0b0110011" cannot be
#   expressed, so nothing below can actually discriminate one instruction from
#   another yet; the matchers are field *positions* only.
# - Nor does it say where a segment lands inside the assembled field. For
#   imm_s, (7,12) is imm[4:0] and (25,32) is imm[11:5]; for imm_b and imm_j
#   the scramble is worse. A segment needs a destination offset (and the
#   immediates need a sign-extension rule) before a decoder can be generated.

from __future__ import annotations

from ..field_match import InstrFieldMatch

ILEN_BYTES = 4          # RV32I is fixed-length; no length decoder needed

# --- register / function fields --------------------------------------------
OPCODE = InstrFieldMatch("opcode", ((0, 7),))
RD     = InstrFieldMatch("rd",     ((7, 12),))
FUNCT3 = InstrFieldMatch("funct3", ((12, 15),))
RS1    = InstrFieldMatch("rs1",    ((15, 20),))
RS2    = InstrFieldMatch("rs2",    ((20, 25),))
FUNCT7 = InstrFieldMatch("funct7", ((25, 32),))
# --- immediates, one per instruction format --------------------------------
IMM_I = InstrFieldMatch("imm_i", ((20, 32),))                       # imm[11:0]
IMM_S = InstrFieldMatch("imm_s", ((7, 12), (25, 32)))               # imm[4:0], imm[11:5]
IMM_B = InstrFieldMatch("imm_b", ((7, 8), (8, 12),                  # imm[11], imm[4:1]
                                  (25, 31), (31, 32)))              # imm[10:5], imm[12]
IMM_U = InstrFieldMatch("imm_u", ((12, 32),))                       # imm[31:12]
IMM_J = InstrFieldMatch("imm_j", ((12, 20), (20, 21),               # imm[19:12], imm[11]
                                  (21, 31), (31, 32)))              # imm[10:1], imm[20]
SHAMT = InstrFieldMatch("shamt", ((20, 25),))                       # slli/srli/srai
