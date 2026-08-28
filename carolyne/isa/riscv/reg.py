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
# it, and a stage body reads it as ctx.pc() off the generator's context.
#
# `RegFile` below is a module-level SHARED INSTANCE with `x_file()` as its
# builder, because IsaBase matches register files by identity and the operand
# rules that target this class are module constants too. The class itself is
# imported under an alias so this name can be the instance.
#
# `ImmTarget` is what an immediate operand points at: an Intermediate, not a
# RegFile, so it allocates no PRF and never reaches rename.

from __future__ import annotations

from ..reg import Intermediate, RegFile as _RegFileType

X_LEN = 32          # register width; RV32I by definition


def x_file() -> _RegFileType:
    """Build the integer register class x0..x31; x0 reads as zero, writes vanish."""
    return _RegFileType("x", X_LEN, 32, const_regs={0: 0})


RegFile   = x_file()                        # the instance operands and the ISA share
ImmTarget = Intermediate(X_LEN, "imm")      # what an immediate operand targets
