# A renamed ONE-REGISTER class through the whole machine — the x86-FLAGS
# shape the contract promises needs zero special-casing in uarch. The class
# has index width 0, so every record drops its ar_idx and every consumer
# must name register 0 as a SIGNAL where it names a decoded index otherwise.
#
# The ISA here is throwaway: two classes, four µops, two units. What it pins
# is the engine, not any description.

from __future__ import annotations

import inspect

from kathryn import build_model, mux, reset, wire, zif
from kathryn.signal import to_ref

from carolyne.isa import (AtomicOperand, FieldRef, InstrFieldMatch, InstrValueMatch, IsaBase,
                          Mop, Operand, OperandRole, RegFile, TargetKind, Uop, UopSeq)
from carolyne.isa.exec_unit import ExecUnitBase
from carolyne.isa.exec_unit_util import drive_by_uop, uop_hit
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType
from carolyne.uarch.o3.dispatch import Dispatch
from examples.o3.core.build import build_machine

SRC, DEST = OperandRole.SRC, OperandRole.DEST
ARCH      = TargetKind.ARCH

G   = RegFile("g",   32, 4, const_regs={0: 0})
ACC = RegFile("acc", 32, 1)

A_S1   = AtomicOperand(SRC,  "src_1",    reg_file=G)
A_S2   = AtomicOperand(SRC,  "src_2",    reg_file=G)
A_SACC = AtomicOperand(SRC,  "src_acc",  reg_file=ACC)
A_D1   = AtomicOperand(DEST, "dest_1",   reg_file=G)
A_DACC = AtomicOperand(DEST, "dest_acc", reg_file=ACC)

OP = InstrFieldMatch("op", ((0, 6),))
RS = InstrFieldMatch("rs", ((6, 8),))
RT = InstrFieldMatch("rt", ((8, 10),))
RD = InstrFieldMatch("rd", ((10, 12),))

O_RS   = Operand(A_S1,   ARCH, FieldRef("rs"), matcher=RS)
O_RT   = Operand(A_S2,   ARCH, FieldRef("rt"), matcher=RT)
O_RD   = Operand(A_D1,   ARCH, FieldRef("rd"), matcher=RD)
O_SACC = Operand(A_SACC, ARCH)                       # one register: no index
O_DACC = Operand(A_DACC, ARCH)

ADD     = Uop("ADD",     0, srcs=(O_RS, O_RT), dests=(O_RD,))
TOACC   = Uop("TOACC",   1, srcs=(O_RS,),      dests=(O_DACC,))
FROMACC = Uop("FROMACC", 2, srcs=(O_SACC,),    dests=(O_RD,))
BR      = Uop("BR",      3, srcs=(O_RS, O_RT), specified_feature=("is_branch",))


class TinyAlu(ExecUnitBase):
    def exec_stage(self, stage_idx, src, api):
        a, b, acc = (api.get_src(src, A_S1), api.get_src(src, A_S2), api.get_src(src, A_SACC))
        result  = wire(32, "t_result")
        drive_by_uop(result, src, ((ADD, a + b), (FROMACC, acc)))
        with zif(uop_hit(src, (ADD, FROMACC))):
            api.wb_reg(A_D1, result)
        with zif(uop_hit(src, TOACC)):
            api.wb_reg(A_DACC, a)
        api.declare_fin(src)
        return None


class TinyBr(ExecUnitBase):
    def exec_stage(self, stage_idx, src, api):
        a, b = api.get_src(src, A_S1), api.get_src(src, A_S2)
        npc  = to_ref(src[0].npc)
        actual_npc = mux(a == b, to_ref(src[0].pc) + 8, npc)
        mis_pred = wire(1, "t_mis"); mis_pred *= actual_npc != npc
        suc_pred = wire(1, "t_suc"); suc_pred *= actual_npc == npc
        api.declare_mis_pred(mis_pred, actual_npc)
        api.declare_suc_pred(suc_pred)
        api.declare_fin(src)
        return None


def tiny_isa() -> IsaBase:
    alu = TinyAlu("alu", (ADD, TOACC, FROMACC),
                  src_operands=(A_S1, A_S2, A_SACC), dest_operands=(A_D1, A_DACC))
    br  = TinyBr("control", (BR,), src_operands=(A_S1, A_S2), needs=("pc", "npc"))
    mops = tuple(Mop(matcher_field=OP, matcher_value=InstrValueMatch((code,)),
                     uop_seq=(UopSeq(uops=(uop,)),))
                 for code, uop in enumerate((ADD, TOACC, FROMACC, BR)))
    return IsaBase(name="tiny", pc_width=32, pc_align=4, ilen_bytes=4, dlen_bytes=4,
                   reset_pc=0, reg_files=(G, ACC),
                   atomic_operands=(A_S1, A_S2, A_SACC, A_D1, A_DACC),
                   operands=(O_RS, O_RT, O_RD, O_SACC, O_DACC),
                   exec_units=(alu, br), uops=(ADD, TOACC, FROMACC, BR), mops=mops)


def tiny_config() -> CPUO3_Config:
    isa = tiny_isa()
    return CPUO3_Config(isa=isa, fe_lanes=2, commit_lanes=2,
                        phy_specs=((G, 8), (ACC, 4)),
                        rsv_specs=(RsvSpec(True,  4, (isa.unit("alu"),),     RsvType.RSV_EXEC),
                                   RsvSpec(False, 4, (isa.unit("control"),), RsvType.RSV_BRANCH)),
                        rob_depth=8, sptag_len=3, st_buf_depth=4,
                        instr_mem_idx_width=6, data_mem_idx_width=6)


def test_a_machine_with_a_renamed_one_register_class_elaborates():
    # rename (warm_rts, rename_src_operand), the ROB's retire and the
    # stations all size an index of width 0 for `acc`; a branch forces the
    # acc destination active, so its rename port is exercised on every lane.
    reset()
    machine = build_model(build_machine(tiny_config()), debug=True)
    assert set(machine.core.dbg_reg_arch) == {"g", "acc"}


def test_the_implicit_register_reaches_the_rename_table_as_a_signal():
    # Rt.write_entry compares the index in a zif; a Python 0 there is a bool.
    source = inspect.getsource(Dispatch.warm_rts)
    assert "ar_idx = val(1, 0)" in source
    assert "ar_idx = 0\n" not in source
