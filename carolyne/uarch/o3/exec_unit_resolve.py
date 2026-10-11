# BranchResolve: a branch outcome stored in flip-flops, so the squash and
# resolve fan-outs start at a register and never at the branch compare.
#
#   cycle N    branch stage:  compare ─> mis_fire ─> mis_pend (reg)
#                             record  ─> tag, rob_idx, dest regs, redirect_pc (regs)
#   cycle N+1  fire():        zif(mis_pend) ─> core.on_mis_pred(tag, rob_idx, redirect_pc, renames)
#                             zif(suc_pend) ─> core.on_suc_pred(tag, rob_idx)
#
# - a resolve in the cycle a stored squash fires is dropped (`& ~mis_pend`):
#   the branch station issues in order, so that branch is younger and killed
# - the record fields are copied every cycle (ungated); they are read only in
#   the cycle after a pend bit is set

from typing import List, Tuple

from kathryn        import reg, ungated, wire, zif
from kathryn.signal import to_ref

from carolyne.uarch.o3.common_field  import ROB_DES_IDX, SPEC_TAG
from carolyne.uarch.o3.operand_field import PR_IDX, field_name


class BranchResolve:
    """The registers one branch complex stores its outcome in, and the fan-out
    they fire one cycle later.

    - built inside the complex's stage body, so the registers belong to the
      complex's module
    """

    def __init__(self, config, label: str, src, arch_dest_atm_oprs):
        row = src[0]
        self.mis_pend    = reg(1, f"{label}_mis_pend")
        self.suc_pend    = reg(1, f"{label}_suc_pend")
        self.tag         = reg(config.sptag_len,     f"{label}_res_tag")
        self.rob_idx     = reg(config.rob_idx_width, f"{label}_res_rob")
        self.redirect_pc = reg(config.pc_width,      f"{label}_res_redirect")
        self.renames     : List[Tuple[object, object]] = []    # (atm_opr, stored phy idx)
        self.label       = label
        self.has_mis     = False
        self.has_suc     = False
        self.mis_pend.reset(0)
        self.suc_pend.reset(0)

        tag, rob_idx = self.tag, self.rob_idx
        with ungated():
            tag     |= to_ref(getattr(row, SPEC_TAG))
            rob_idx |= to_ref(getattr(row, ROB_DES_IDX))
            for atm_opr in arch_dest_atm_oprs:
                phy_idx  = reg(config.phy_idx_width(atm_opr.reg_file), f"{label}_res_{atm_opr.name}")
                phy_idx |= to_ref(getattr(row, field_name(PR_IDX, atm_opr)))
                self.renames.append((atm_opr, phy_idx))

    def store_mis_pred(self, dyn_cond, next_pc):
        """Set mis_pend and keep the redirect pc."""
        self.has_mis = True
        mis_fire  = wire(1, f"{self.label}_mis_fire")
        mis_fire *= dyn_cond & ~self.mis_pend
        mis_pend, redirect_pc = self.mis_pend, self.redirect_pc
        with ungated():
            mis_pend    |= mis_fire
            redirect_pc |= next_pc

    def store_suc_pred(self, dyn_cond):
        """Set suc_pend."""
        self.has_suc = True
        suc_fire  = wire(1, f"{self.label}_suc_fire")
        suc_fire *= dyn_cond & ~self.mis_pend
        suc_pend  = self.suc_pend
        with ungated():
            suc_pend |= suc_fire

    def fire(self, core):
        """The fan-outs, from the stored registers; call outside any stage."""
        if self.has_mis:
            with zif(self.mis_pend):
                core.on_mis_pred(self.tag, self.rob_idx, self.redirect_pc, self.renames)
        if self.has_suc:
            with zif(self.suc_pend):
                core.on_suc_pred(self.tag, self.rob_idx)
