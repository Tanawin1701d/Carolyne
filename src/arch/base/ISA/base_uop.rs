use crate::arch::base::ISA::base_opr::OperandItf;
use std::sync::atomic::{AtomicU64};

pub static NEXT_UOP_ID: AtomicU64 = AtomicU64::new(0);

pub trait UopItf{


    fn get_amt_src_opr(&self) -> usize;
    fn get_src_opr_itf(&mut self, index: usize) -> &mut dyn OperandItf;
    fn get_amt_dst_opr(&self) -> usize;
    fn get_dst_opr_itf(&mut self, index: usize) -> &mut dyn OperandItf;
    fn get_id(&self) -> u64;
    fn assign_id(&mut self);
    fn is_ready_to_execute(&self) -> bool;
    fn execute(&mut self);

}