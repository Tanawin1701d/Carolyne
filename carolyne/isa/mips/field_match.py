# Where MIPS32's encoding fields are in the 32-bit instruction word
# (uop_contract.md §1.3). Segments are (start, end) with end EXCLUSIVE and
# bit 0 = LSB, so opcode = (26, 32) is bits 31..26.
#
# MIPS32 is fixed 32-bit, so ILEN_BYTES is the constant 4 and no length
# decoder is needed; the addressing scalars are beside the fields as one
# group. RESET_PC is the ARCHITECTURAL reset vector: MIPS fixes it, so the
# description states it and a machine does not choose one.
#
# The unions are where one funct value names two instructions and a second
# field decides: srl/rotr (rs field), srlv/rotrv and seb/seh (sa field).
# BITFIELD is ext/ins's two 5-bit positions read as ONE immediate (imm.py).
#
# The three FORMATS are InstrFieldMatch unions, DECLARED but NOT USED: Mop
# has no format slot. Fields are unioned in ascending first-bit order, so
# each format's segments tile the word exactly once (pinned in test_mips.py).
#
# NOT here: how the matched bits become a VALUE — that is stated per operand
# by `imm_extract` (imm.py).

from __future__ import annotations

from ..field_match import InstrFieldMatch, InstrValueMatch
from .reg import X_LEN


def val(*values: int) -> InstrValueMatch:
    """One match value per segment, in the field's own segment order."""
    return InstrValueMatch(values)


# --- instruction addressing (the scalars IsaBase takes) ----------------------
PC_WIDTH   = X_LEN      # program counter is 32 bits
PC_ALIGN   = 4          # instruction addresses are 4-byte aligned
ILEN_BYTES = 4          # MIPS32 is fixed-length; no length decoder needed
DLEN_BYTES = 4          # widest data access: LW/SW move a 32-bit word
RESET_PC   = 0xBFC00000 # the architectural reset vector: the ISA fixes it

# --- register / function fields --------------------------------------------
OPCODE      = InstrFieldMatch("opcode",      ((26, 32),))     # bits 31..26
RS          = InstrFieldMatch("rs",          ((21, 26),))     # bits 25..21
RT          = InstrFieldMatch("rt",          ((16, 21),))     # bits 20..16
RD          = InstrFieldMatch("rd",          ((11, 16),))     # bits 15..11
SA          = InstrFieldMatch("sa",          (( 6, 11),))     # bits 10..6
FUNCT       = InstrFieldMatch("funct",       (( 0,  6),))     # bits 5..0
IMM16       = InstrFieldMatch("imm16",       (( 0, 16),))     # bits 15..0
INSTR_INDEX = InstrFieldMatch("instr_index", (( 0, 26),))     # bits 25..0

# one funct, two instructions: the second field tells them apart
FUNCT_RS = FUNCT | RS                          # srl (rs 0) vs rotr (rs 1)
FUNCT_SA = FUNCT | SA                          # srlv/rotrv (sa 0/1); seb/seh (sa 16/24)
BITFIELD = SA.union(RD, name="bitfield")       # ext/ins: pos in sa, size-1 or msb in rd

# --- the three instruction formats ------------------------------------------
R_TYPE = FUNCT.union(SA, RD, RT, RS, OPCODE, name="r_type")   # opcode rs rt rd sa funct
I_TYPE = IMM16.union(RT, RS, OPCODE,         name="i_type")   # opcode rs rt imm16
J_TYPE = INSTR_INDEX.union(OPCODE,           name="j_type")   # opcode instr_index

FORMATS = (R_TYPE, I_TYPE, J_TYPE)
