# RV32I architectural register classes (uop_contract.md §1.1 / §6 deliverable
# one), plus the target an immediate operand points at. Description data
# only — no hardware, no Kathryn.
#
# Decisions (2026-08-14):
# - One renamed class: x0..x31, X_LEN bits. x0 is declared through
#   `const_regs` rather than special-cased anywhere: rename bypasses reads of
#   it and discards writes to it, which is exactly RISC-V's hardwired-zero
#   rule.
# - PC is deliberately NOT a register class. It was drafted as a 1-entry file
#   and removed: the program counter is not architectural state the engine
#   renames and reads through a PRF port, it is front-end / ROB state that
#   already has to exist for redirects and exceptions. Modelling it as a
#   reg file would have every branch allocate a physical register for a value
#   the machine tracks anyway.
#   Consequence, and an open contract question: the pc-relative µops (auipc,
#   and the link value the jumps write) need the *instruction's own PC* as an
#   input. They get it from the µop record, not from a source operand — see
#   the GAPS block in rv32i.py. Nothing in this layer can state that yet.
# - `RegFile` here is a module-level SHARED INSTANCE, with `x_file()` as the
#   builder behind it. IsaBase matches register files by identity, so
#   everything that names this class must name the same object: the operand
#   rules of operand.py are module constants, so the class they target has to
#   be one too. The cost is real and accepted: two rv32i() builds in one
#   process share it, and a caller who wants genuinely independent
#   descriptions calls x_file() and builds its own operands. Nothing mutates
#   a RegFile, so sharing is safe; only identity makes it visible.
#   The class itself is imported under an alias so this name can be the
#   instance — rebinding `RegFile` to the value it produced would leave
#   x_file() calling an instance on its second call.
# - `ImmTarget` is what an immediate operand points at: one Intermediate,
#   shared, standing for "this value comes from the encoding, not from a
#   register class". It is deliberately NOT a RegFile, so it allocates no
#   PRF and never reaches rename — IsaBase.used_reg_files() skips it.

from __future__ import annotations

from ..reg import Intermediate, RegFile as _RegFileType

X_LEN = 32          # register width; RV32I by definition


def x_file() -> _RegFileType:
    """Build the integer register class x0..x31; x0 reads as zero, writes vanish."""
    return _RegFileType("x", X_LEN, 32, const_regs={0: 0})


RegFile   = x_file()                        # the instance operands and the ISA share
ImmTarget = Intermediate(X_LEN, "imm")      # what an immediate operand targets
