use std::sync::atomic::{AtomicU64};

static NEXT_OPR_ID: AtomicU64 = AtomicU64::new(0);
pub trait OperandItf {

    fn is_valid(&self)           -> bool;
    fn get_arch_reg_index(&self)     -> usize;
    fn get_arch_table_idx(&self) -> usize;
    fn get_phy_reg_index(&self)      -> usize;
    fn get_phy_table_idx(&self)  -> usize;
}





