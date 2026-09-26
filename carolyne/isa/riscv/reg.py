# RV32I architectural register classes (uop_contract.md §1.1 / §6 deliverable
# one), plus the target an immediate operand points at. Description data
# only — no hardware, no Kathryn.
#
# One renamed class: x0..x31, X_LEN bits, with x0 declared through
# `const_regs` — rename bypasses reads of it and discards writes to it.
#
# PC is NOT a register class: it is front-end / ROB state, not something the
# engine renames through a PRF port. Consequence: the pc-relative µops (auipc,
# the jumps' link value) never name PC as an operand — the µop record carries
# it, and a stage body reads it off that record.
#
# `X_FILE` is a module-level SHARED INSTANCE with `build_x_file()` as its
# builder, because IsaBase matches register files by identity and the operand
# rules that target this class are module constants too.
#
# `IMM_TARGET` is what an immediate operand points at: an Intermediate, not a
# RegFile, so it allocates no PRF and never goes through rename.

from __future__ import annotations

from ..reg import Intermediate, RegFile

X_LEN = 32                  # register width; RV32I by definition
SIGN  = 1 << (X_LEN - 1)    # the sign bit, for signed-order tricks


def build_x_file() -> RegFile:
    """Build the integer register class x0..x31; x0 reads as zero, writes vanish."""
    return RegFile("x", X_LEN, 32, const_regs={0: 0})


X_FILE     = build_x_file()                 # the instance operands and the ISA share
IMM_TARGET = Intermediate(X_LEN, "imm")     # what an immediate operand targets
