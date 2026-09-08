# SystemExecUnit — fence, ecall and ebreak: the µops that name no operand and
# compute no value. A natural-Kathryn exec_stage body (isa/exec_unit.py), even
# though this one builds nothing: it declares only that the µop is done.
#
# FENCE is a NO-OP on this machine. Memory accesses issue from ONE in-order
# station, so there is no reordering for a fence to hold back.
#
# LIMIT: ECALL and EBREAK should TRAP, and trap policy does not exist yet
# (uop_contract.md §6, step 5 of the FU plan). Until it does they retire like
# any other instruction, so a program that executes one simply continues.
#
# One stage, so exec_stage returns None; no register is written, so no wb_reg.

from __future__ import annotations

from ..exec_unit import ExecUnitBase


class SystemExecUnit(ExecUnitBase):
    """fence / ecall / ebreak: finish, and write nothing."""

    def exec_stage(self, stage_idx, src, api):
        api.declare_fin(src)
        return None
