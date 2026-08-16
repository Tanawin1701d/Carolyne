# Where RV32I's encoding fields live in the 32-bit instruction word
# (uop_contract.md §1.3). Segments are (start, end) with end EXCLUSIVE and
# bit 0 = LSB, so funct7 = (25, 32) is bits 31..25.
#
# Decisions (2026-08-14):
# - RV32I is fixed 32-bit, so `ilen` is the constant 4 and no length decoder
#   is needed. The field has no type in the isa layer yet (§6 deliverable
#   three); ILEN_BYTES below is the value it will carry.
#   (2026-08-16: IsaBase grew `ilen_bytes`, so ILEN_BYTES is now carried rather
#   than merely declared, and PC_WIDTH / PC_ALIGN joined it — one group, since
#   all three answer "where does an instruction sit and how long is it".)
# - The scrambled immediates (S/B/J) are the reason InstrFieldMatch takes a
#   TUPLE of segments. imm_b is written as four segments rather than merged
#   ranges even where two are adjacent — (7,8) is imm[11] and (8,12) is
#   imm[4:1], and merging them would erase that they land in different places.
#
# Decision (2026-08-15):
# - The six base FORMATS are InstrFieldMatch unions of the fields they contain,
#   not a new type. A format IS "one rule spanning several fields", which is
#   exactly what union() gives, and keeping formats in the same type means a
#   consumer that can read a field rule can read a format for free. They are
#   DECLARED, NOT CONSUMED: Mop has no format slot, so rv32i.py names the
#   format of each opcode group in a comment. Grouping the mop table by format
#   instead of by opcode was considered and rejected — one I-type Mop would
#   have to cover four different opcodes (LOAD, OP-IMM, JALR, SYSTEM), and a
#   matcher naming one opcode field cannot say four values.
# - `val(...)` is the package's shorthand for an InstrValueMatch, and it lives
#   here beside the fields those values are compared against — the two halves
#   are separate types, so the one place that reads as a pair is this file.
#
# KNOWN GAPS — this file is where the encoding side runs out of road, and the
# missing pieces belong in the contract, not here:
# - A rule can DISCRIMINATE but not EXTRACT. Nothing says where a segment lands
#   inside the assembled field: for imm_s, (7,12) is imm[4:0] and (25,32) is
#   imm[11:5]; for imm_b and imm_j the scramble is worse. A segment needs a
#   destination offset (and the immediates a sign-extension rule) before an
#   immediate can be built — picking the instruction now works, reading its
#   operand value does not.

from __future__ import annotations

from ..field_match import InstrFieldMatch, InstrValueMatch
from .reg import X_LEN


def val(*values: int) -> InstrValueMatch:
    """One match value per segment of the field this will be paired with.

    Shorthand only, and it exists for readability at the call site: the
    one-segment case spelled out is `InstrValueMatch((0b000,))`, whose lone
    trailing comma is exactly the kind of thing that gets dropped. `val(0b000)`
    cannot lose it. Segment order is the field's — `val(0b000, 0b0100000)`
    beside FUNCT3_7 is funct3 then funct7, because that is how FUNCT3_7 was
    unioned.
    """
    return InstrValueMatch(values)

# --- instruction addressing (the three scalars IsaBase takes) ---------------
# Grouped here because they are one subject with the field positions below:
# where an instruction sits and how long it is. PC_WIDTH is XLEN by the RV32I
# spec — the PC still has a width even though it is not a register class, and
# reg.py says why it is not one.
PC_WIDTH   = X_LEN      # program counter is XLEN bits
PC_ALIGN   = 4          # instruction addresses are 4-byte aligned (2 with the C ext)
ILEN_BYTES = 4          # RV32I is fixed-length; no length decoder needed

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
