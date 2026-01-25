use std::collections::VecDeque;
use crate::arch::base::ISA::riscv::mop::RiscvMop;

pub struct RiscvISA {
    inflight_mop_queue: VecDeque<RiscvMop>,
    next_fetch_pc     : u64,
    next_commit_pc    : u64,

}