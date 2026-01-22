
use crate::arch::base::ISA::base_opr::{OperandItf};

pub const RISCV_MAX_NUM_SRC_OPRS: usize = 2;
pub const RISCV_MAX_NUM_DST_OPRS: usize = 1;


#[derive(Copy, Clone)]
pub struct RiscvOperand {
    valid          : bool,
    arch_reg_idx   : usize,
    arch_table_idx : usize,
    phy_reg_idx    : usize,
    phy_table_idx  : usize,
}

impl RiscvOperand {

    pub fn new() -> Self { Self::default() }
    pub fn default() -> Self {
        Self {
            valid: false,
            arch_reg_idx: 0,
            arch_table_idx: 0,
            phy_reg_idx: 0,
            phy_table_idx: 0,
        }
    }
}

impl OperandItf for RiscvOperand {

    fn is_valid(&self) -> bool { self.valid }
    fn get_arch_reg_index(&self) -> usize { self.arch_reg_idx }
    fn get_arch_table_idx(&self) -> usize { self.arch_table_idx }
    fn get_phy_reg_index(&self) -> usize { self.phy_reg_idx }
    fn get_phy_table_idx(&self) -> usize { self.phy_table_idx }

}


