/// the interface that connects the ISA to the timing architecture model
use crate::arch::base::ISA::base_uop::UopItf;
use std::sync::atomic::{AtomicU64};
pub static NEXT_MOP_ID: AtomicU64 = AtomicU64::new(0);

pub trait MopItf{

    fn get_amt_uop(&self) -> usize;
    fn get_uop_itf(&mut self, index: usize) -> &mut dyn UopItf;
    fn get_id(&self) -> u64;
    fn assign_id(&mut self);
    fn is_ready_to_execute(&self) -> bool;
    // fn memory_read_back(&self, uop_idx :usize,
    //                     addr: u64,
    //                     data: u64);

}

pub trait ISAItf{

    fn get_ent_pc(&self) -> u64; /// return program counter of the instruction
    fn gen_ent_pc(&self) -> u64; /// return mop id of the instruction
    fn get_cur_mop_from_ent(&self, mop_idx: u64) -> &mut dyn MopItf; /// return mop from ent

    fn get_cmt_pc(&self) -> u64;
    fn is_ready_to_commit(&self) -> bool;
    fn commit_pc(&self, pc: u64);
    fn transfer_mop_to_ent(&self, mop_idx: u64);

    fn memory_read_back(&self, mop_idx: usize,
                        uop_idx: usize,
                        addr: u64,
                        data: u64);
}