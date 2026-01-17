
use crate::arch::base::ISA::base::{OperandItf, UopItf, MopItf, ISAItf};



pub struct RiscvOperand {
    valid          : bool,
    arch_reg_idx   : usize,
    arch_table_idx : usize,
    phy_reg_idx    : usize,
    phy_table_idx  : usize,
}

impl OperandItf for RiscvOperand {

    fn is_valid(&self) -> bool { self.valid }
    fn get_arch_reg_index(&self) -> usize { self.arch_reg_idx }
    fn get_arch_table_idx(&self) -> usize { self.arch_table_idx }
    fn get_phy_reg_index(&self) -> usize { self.phy_reg_idx }
    fn get_phy_table_idx(&self) -> usize { self.phy_table_idx }

}

pub const RISCV_MAX_NUM_SRC_OPRS: usize = 2;
pub const RISCV_MAX_NUM_DST_OPRS: usize = 1;

