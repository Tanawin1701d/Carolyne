use crate::arch::base::ISA::base_mop::MopItf;

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