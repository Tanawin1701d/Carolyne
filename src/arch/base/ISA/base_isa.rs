use crate::arch::base::ISA::base_mop::MopItf;

pub trait ISAItf{

    fn get_next_fetch_pc(&self) -> u64; /// return program counter of the instruction
    fn gen_next_fetch_mop(&self, raw_instr: u64) -> &mut dyn MopItf; /// return mop id of the instruction
    fn get_next_commit_pc(&self) -> u64;
    fn is_ready_to_commit(&self) -> bool;
    fn commit_pc(&self);
}