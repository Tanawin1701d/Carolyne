use std::collections::VecDeque;
use crate::arch::base::ISA::base_isa::ISAItf;
use crate::arch::base::ISA::base_mop::MopItf;
use crate::arch::base::ISA::riscv::mop::RiscvMop;

pub struct RiscvISA {
    inflight_mop_queue: VecDeque<RiscvMop>,
    next_fetch_pc     : u64,
    next_commit_pc    : u64,
}

impl RiscvISA {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn default() -> Self {
        Self {
            inflight_mop_queue: VecDeque::new(),
            next_fetch_pc: 0,
            next_commit_pc: 0,
        }
    }

    pub fn inc_next_fetch_pc(&mut self) {
        self.next_fetch_pc += 4;
    }

    pub fn inc_next_commit_pc(&mut self) {
        self.next_commit_pc += 4;
    }
    
    pub fn tryCommit(&mut self) -> Option<RiscvMop> {
        let ready = self.inflight_mop_queue
                          .front()
                          .map(|m| m.is_ready_to_execute())
                          .unwrap_or(false);

        self.inflight_mop_queue
            .front()
            .is_some_and(|m| m.is_ready_to_execute())
            .then_some(())
            .and_then(|_| self.inflight_mop_queue.pop_front())
    }

    
}



impl ISAItf for RiscvISA {
    type IWIDTH = u32;
    fn get_next_fetch_pc(&self) -> u64 { self.next_fetch_pc }
    fn gen_next_fetch_mop(&self, raw_instr: Self::IWIDTH) -> &mut dyn MopItf { unimplemented!() }
    fn get_next_commit_pc(&self) -> u64 { self.next_commit_pc }
    fn is_ready_to_commit(&self) -> bool { unimplemented!() }
    fn commit_pc(&self) { unimplemented!() }

}