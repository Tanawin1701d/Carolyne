use crate::arch::base::ISA::base_mop::{MopItf, NEXT_MOP_ID};
use crate::arch::base::ISA::base_uop::UopItf;
use crate::arch::base::ISA::riscv::uop::{RiscvUop, RISCV_MAX_NUM_UOPS};

#[derive(Copy, Clone)]
pub struct RiscvMop{
    id        : u64,
    uops      : [RiscvUop; RISCV_MAX_NUM_UOPS],
    uop_cnt   : usize
}

impl RiscvMop{
    pub fn new() -> Self{
        let new_item = Self::default();
        new_item
    }
    pub fn default() -> Self{
        RiscvMop {
            id        : 0,
            uops      : [RiscvUop::default(); RISCV_MAX_NUM_UOPS],
            uop_cnt   : 0,
        }
    }
    
    pub fn add_uop(&mut self, uop: RiscvUop) {
        assert!(self.uop_cnt < RISCV_MAX_NUM_UOPS, "Uop count overflow (RiscvMop)");
        self.uops[self.uop_cnt] = uop;
        self.uops[self.uop_cnt].assign_id();
        self.uop_cnt += 1;
    }
}


impl MopItf for RiscvMop {
    fn get_amt_uop(&self) -> usize {
        self.uop_cnt
    }

    fn get_uop_itf(&mut self, index: usize) -> &mut dyn UopItf {
        &mut self.uops[index]
    }
    
    fn get_id(&self) -> u64 { self.id }

    fn assign_id(&mut self) {
        self.id = NEXT_MOP_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    }
    
    fn is_ready_to_execute(&self) -> bool { 
        
        let mut ready: bool = true;
        for uopIdx in 0..self.uop_cnt {
            ready &= self.uops[uopIdx].is_ready_to_execute();
        }
        ready
    }    
    
}