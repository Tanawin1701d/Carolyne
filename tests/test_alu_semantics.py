# RV32I's ALU semantics run against a FAKE execution context — plain Python
# ints, no arena, no Kathryn. This is the cheapest possible test of an ISA's
# arithmetic, and the fake doubles as usage documentation for the interface
# a stage body is written against:
#
# - the body always EXECUTES: `when(False)` still runs its block in Python,
#   exactly as elaboration would, and only the write inside is suppressed;
# - the WRITE truncates to the destination width, so wraparound comes out the
#   same as 32-bit hardware;
# - a slot the µop never filled reads like an idle wire (here: 0), and the
#   op's guard is what keeps it out of the result.

from contextlib import contextmanager

import pytest

from carolyne.isa.riscv import uop as U
from carolyne.isa.riscv.exec_unit import exec_units
from carolyne.isa.riscv.reg import X_LEN

MASK = (1 << X_LEN) - 1


class FakeCtx:
    """Pure-Python execution context: one µop, one cycle, ints for signals."""

    def __init__(self, uop, pc=0, **srcs):
        self.uop_, self.pc_ = uop, pc
        self.srcs   = srcs          # slot name -> value; an immediate is one
                                    # of these, e.g. src_2=<the assembled imm>
        self.writes = {}            # what the body drove, post-truncation
        self.keeps  = {}
        self._guards = []           # the enclosing when-conditions

    # --- the µop record, read ------------------------------------------------
    def uop_is(self, uop):
        return self.uop_ is uop         # templates match by identity

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


def run(uop, a=0, b=0, pc=0):
    """One µop through the ALU body: srcs in, rd out."""
    ctx = FakeCtx(uop, pc=pc, src_1=a, src_2=b)
    ALU.build_exec(ctx)
    return ctx.writes.get("dest_1")


def test_exactly_one_write_per_uop():
    # The guards are mutually exclusive by construction: one µop, one result,
    # always to rd. Every template the unit lists has to produce one — a
    # register form and its immediate form alike.
    for uop in sorted(ALU.uops, key=lambda u: u.name):
        ctx = FakeCtx(uop, src_1=7, src_2=3)
        ALU.build_exec(ctx)
        assert set(ctx.writes) == {"dest_1"}, uop.name


def test_add_and_sub_wrap_at_32_bits():
    assert run(U.UOP_ADD, 5, 7) == 12
    assert run(U.UOP_ADD, 0xFFFF_FFFF, 1) == 0
    assert run(U.UOP_SUB, 7, 5) == 2
    assert run(U.UOP_SUB, 0, 1) == 0xFFFF_FFFF


def test_the_bitwise_three():
    assert run(U.UOP_AND, 0b1100, 0b1010) == 0b1000
    assert run(U.UOP_OR,  0b1100, 0b1010) == 0b1110
    assert run(U.UOP_XOR, 0b1100, 0b1010) == 0b0110
    # xori rd, rs, -1 is NOT (op.py's comment on XOR).
    assert run(U.UOP_XOR, 0x0F0F_0F0F, 0xFFFF_FFFF) == 0xF0F0_F0F0


def test_shifts_use_only_the_low_five_bits_of_src2():
    assert run(U.UOP_SLL, 1, 31) == 0x8000_0000
    assert run(U.UOP_SLL, 1, 32) == 1                  # sh = 32 & 31 = 0
    assert run(U.UOP_SRL, 0x8000_0000, 31) == 1


def test_srl_zero_fills_where_sra_sign_fills():
    assert run(U.UOP_SRL, 0x8000_0000, 4) == 0x0800_0000
    assert run(U.UOP_SRA, 0x8000_0000, 4) == 0xF800_0000
    assert run(U.UOP_SRA, 0x4000_0000, 4) == 0x0400_0000   # positive: same as SRL
    assert run(U.UOP_SRA, 0x8000_0000, 0) == 0x8000_0000   # by zero: identity
    assert run(U.UOP_SRA, 0xFFFF_FFFF, 31) == 0xFFFF_FFFF  # -1 stays -1


def test_slt_is_signed_where_sltu_is_not():
    minus_one = 0xFFFF_FFFF
    assert run(U.UOP_SLT,  minus_one, 1) == 1
    assert run(U.UOP_SLT,  1, minus_one) == 0
    assert run(U.UOP_SLT,  5, 5) == 0
    assert run(U.UOP_SLTU, minus_one, 1) == 0          # unsigned: huge, not negative
    assert run(U.UOP_SLTU, 1, 2) == 1
    # sltiu rd, rs, 1 is seqz (op.py's comment on SLTU).
    assert run(U.UOP_SLTU, 0, 1) == 1
    assert run(U.UOP_SLTU, 5, 1) == 0


def test_lui_passes_the_assembled_immediate_through():
    # LUI fills only src_2 — src_1 is deliberately not
    # supplied here, the unfilled-slot case the fake's src() documents.
    ctx = FakeCtx(U.UOP_LUI, src_2=0xDEAD_B000)
    ALU.build_exec(ctx)
    assert ctx.writes == {"dest_1": 0xDEAD_B000}


def test_auipc_adds_the_uops_own_pc():
    assert run(U.UOP_AUIPC, b=0x0000_1000, pc=0x8000_0000) == 0x8000_1000
    assert run(U.UOP_AUIPC, b=0x0000_2000, pc=0xFFFF_F000) == 0x0000_1000  # wraps


def test_an_op_the_guards_do_not_cover_writes_nothing():
    # A kind the body never names leaves rd undriven — the shape that makes
    # the guards, not the reads, the thing protecting the result.
    ctx = FakeCtx(U.UOP_FENCE, src_1=7, src_2=3)
    ALU.build_exec(ctx)
    assert ctx.writes == {}
