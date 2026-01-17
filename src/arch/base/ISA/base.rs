use crate::arch::base::arf::arf::InstrWidth;

pub trait OperandItf {

    fn is_valid(&self)           -> bool;
    fn get_arch_reg_index(&self)     -> usize;
    fn get_arch_table_idx(&self) -> usize;
    fn get_phy_reg_index(&self)      -> usize;
    fn get_phy_table_idx(&self)  -> usize;
}

pub trait UopItf{


    fn get_amt_src_opr(&self) -> usize;
    fn get_src_opr_itf(&mut self, index: usize) -> &mut dyn OperandItf;
    fn get_amt_dst_opr(&self) -> usize;
    fn get_dst_opr_itf(&mut self, index: usize) -> &mut dyn OperandItf;
    fn get_id(&self) -> u64;
    fn is_ready_to_execute(&self) -> bool;
    fn execute(&mut self);

}

pub trait MopItf{

    fn get_amt_uop(&self) -> usize;
    fn get_uop_itf(&self, index: usize) -> &mut dyn UopItf;
    fn get_id(&self) -> u64;
    fn is_ready_to_execute(&self) -> bool;
    fn memory_read_back(&self, uop_idx :usize,
                               addr: u64,
                               data: u64);

}

/// the interface that connects the ISA to the timing architecture model
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