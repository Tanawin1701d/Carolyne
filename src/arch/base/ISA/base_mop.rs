/// the interface that connects the ISA to the timing architecture model
use crate::arch::base::ISA::base_uop::UopItf;
use std::sync::atomic::{AtomicU64};
pub static NEXT_MOP_ID: AtomicU64 = AtomicU64::new(0);

pub trait MopItf{
    fn get_pc(&self) -> u64;
    fn get_amt_uop(&self) -> usize;
    fn get_uop_itf(&mut self, index: usize) -> &mut dyn UopItf;
    fn get_id(&self) -> u64;
    fn assign_id(&mut self);
    fn is_ready_to_execute(&self) -> bool;
    // fn memory_read_back(&self, uop_idx :usize,
    //                     addr: u64,
    //                     data: u64);

}