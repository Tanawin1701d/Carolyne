# RV32I's ALU semantics run against a FAKE ExecContext — plain Python ints,
# no arena, no Kathryn. This is the cheapest possible test of an ISA's
# arithmetic, and the fake doubles as usage documentation for the interface
# (carolyne/isa/exec_context.py):
#
# - the body always EXECUTES: `when(False)` still runs its block in Python,
#   exactly as elaboration would, and only the write inside is suppressed;
# - the WRITE truncates to the destination width, so wraparound comes out the
#   same as 32-bit hardware;
# - a slot the µop never filled reads like an idle wire (here: 0), and the
#   op's guard is what keeps it out of the result.

from contextlib import contextmanager

import pytest

from carolyne.isa import ExecContext
from carolyne.isa.riscv import op as O
from carolyne.isa.riscv.exec_unit import exec_units
from carolyne.isa.riscv.reg import X_LEN

MASK = (1 << X_LEN) - 1


class FakeCtx:
    """Pure-Python ExecContext: one µop, one cycle, ints for signals."""

    def __init__(self, op, pc=0, **srcs):
        self.op_, self.pc_ = op, pc
        self.srcs   = srcs          # slot name -> value; an immediate is one
                                    # of these, e.g. src_2=<the assembled imm>
        self.writes = {}            # what the body drove, post-truncation
        self.keeps  = {}
        self._guards = []           # the enclosing when-conditions

    # --- the µop record, read ------------------------------------------------
    def op_is(self, op):
        return self.op_ == op

    def src(self, name):
        return self.srcs.get(name, 0)      # unfilled slot: idle wire

    def pc(self):
        return self.pc_

    # --- the µop record, written ---------------------------------------------
    def write(self, name, value):
        if all(self._guards):
            self.writes[name] = int(value) & MASK

    # --- stage-to-stage state ------------------------------------------------
    def keep(self, name, value):
        if all(self._guards):
            self.keeps[name] = int(value) & MASK

    def kept(self, name):
        return self.keeps[name]

    # --- flow ----------------------------------------------------------------
    @contextmanager
    def when(self, cond):
        self._guards.append(bool(cond))
        try:
            yield
        finally:
            self._guards.pop()

    def until(self, cond):
        raise NotImplementedError("FakeCtx evaluates one cycle of arithmetic")

    def while_(self, cond):
        raise NotImplementedError("FakeCtx evaluates one cycle of arithmetic")


ALU = next(u for u in exec_units() if u.name == "alu")


def run(op, a=0, b=0, pc=0):
    """One µop through the ALU body: srcs in, rd out."""
    ctx = FakeCtx(op, pc=pc, src_1=a, src_2=b)
    ALU.build_exec(ctx)
    return ctx.writes.get("dest_1")


def test_the_fake_satisfies_the_contract():
    assert isinstance(FakeCtx(O.ADD), ExecContext)


def test_exactly_one_write_per_op():
    # The guards are mutually exclusive by construction: one op, one result,
    # always to rd.
    for op in sorted(ALU.ops, key=lambda o: o.name):
        ctx = FakeCtx(op, src_1=7, src_2=3)
        ALU.build_exec(ctx)
        assert set(ctx.writes) == {"dest_1"}, op.name


def test_add_and_sub_wrap_at_32_bits():
    assert run(O.ADD, 5, 7) == 12
    assert run(O.ADD, 0xFFFF_FFFF, 1) == 0
    assert run(O.SUB, 7, 5) == 2
    assert run(O.SUB, 0, 1) == 0xFFFF_FFFF


def test_the_bitwise_three():
    assert run(O.AND, 0b1100, 0b1010) == 0b1000
    assert run(O.OR,  0b1100, 0b1010) == 0b1110
    assert run(O.XOR, 0b1100, 0b1010) == 0b0110
    # xori rd, rs, -1 is NOT (op.py's comment on XOR).
    assert run(O.XOR, 0x0F0F_0F0F, 0xFFFF_FFFF) == 0xF0F0_F0F0


def test_shifts_use_only_the_low_five_bits_of_src2():
    assert run(O.SLL, 1, 31) == 0x8000_0000
    assert run(O.SLL, 1, 32) == 1                  # sh = 32 & 31 = 0
    assert run(O.SRL, 0x8000_0000, 31) == 1


def test_srl_zero_fills_where_sra_sign_fills():
    assert run(O.SRL, 0x8000_0000, 4) == 0x0800_0000
    assert run(O.SRA, 0x8000_0000, 4) == 0xF800_0000
    assert run(O.SRA, 0x4000_0000, 4) == 0x0400_0000   # positive: same as SRL
    assert run(O.SRA, 0x8000_0000, 0) == 0x8000_0000   # by zero: identity
    assert run(O.SRA, 0xFFFF_FFFF, 31) == 0xFFFF_FFFF  # -1 stays -1


def test_slt_is_signed_where_sltu_is_not():
    minus_one = 0xFFFF_FFFF
    assert run(O.SLT,  minus_one, 1) == 1
    assert run(O.SLT,  1, minus_one) == 0
    assert run(O.SLT,  5, 5) == 0
    assert run(O.SLTU, minus_one, 1) == 0          # unsigned: huge, not negative
    assert run(O.SLTU, 1, 2) == 1
    # sltiu rd, rs, 1 is seqz (op.py's comment on SLTU).
    assert run(O.SLTU, 0, 1) == 1
    assert run(O.SLTU, 5, 1) == 0


def test_lui_passes_the_assembled_immediate_through():
    # MOV_IMM's µop fills only src_2 (UOP_LUI) — src_1 is deliberately not
    # supplied here, the unfilled-slot case the fake's src() documents.
    ctx = FakeCtx(O.MOV_IMM, src_2=0xDEAD_B000)
    ALU.build_exec(ctx)
    assert ctx.writes == {"dest_1": 0xDEAD_B000}


def test_auipc_adds_the_uops_own_pc():
    assert run(O.AUIPC, b=0x0000_1000, pc=0x8000_0000) == 0x8000_1000
    assert run(O.AUIPC, b=0x0000_2000, pc=0xFFFF_F000) == 0x0000_1000  # wraps


def test_an_op_the_guards_do_not_cover_writes_nothing():
    # A kind the body never names leaves rd undriven — the shape that makes
    # the guards, not the reads, the thing protecting the result.
    ctx = FakeCtx(O.FENCE, src_1=7, src_2=3)
    ALU.build_exec(ctx)
    assert ctx.writes == {}
