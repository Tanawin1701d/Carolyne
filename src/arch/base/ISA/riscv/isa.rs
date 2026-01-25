use std::collections::VecDeque;
use crate::arch::base::ISA::riscv::mop::RiscvMop;

pub struct RiscvISA {
    inflight_mop_queue: VecDeque<RiscvMop>,
    inflight_mop_q
}