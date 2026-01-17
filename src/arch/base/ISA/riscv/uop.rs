use crate::arch::base::ISA::base::{OperandItf, UopItf};
use crate::arch::base::ISA::riscv::opr::{RiscvOperand, RISCV_MAX_NUM_SRC_OPRS, RISCV_MAX_NUM_DST_OPRS};

pub struct RiscvUop {
    src_oprs    : [RiscvOperand; RISCV_MAX_NUM_SRC_OPRS],
    dst_oprs    : [RiscvOperand; RISCV_MAX_NUM_DST_OPRS],
    id          : u64,
    opcode      : u32,
    sub_opcode  : u32,
    imm         : u32,
    src_opr_cnt : usize,
    dest_opr_cnt: usize,
}

impl RiscvUop {
    
    
    
    fn check_ready(oprs: &[RiscvOperand]) -> bool {
        for opr in oprs {
            if !opr.is_valid() {
                return false;
            }
        }
        true
    }
}

impl UopItf for RiscvUop {


    fn get_amt_src_opr(&self) -> usize {
        self.src_opr_cnt
    }

    fn get_src_opr_itf(&mut self, index: usize) -> &mut dyn OperandItf {
        &mut self.src_oprs[index]
    }

    fn get_amt_dst_opr(&self) -> usize {
        1
    }

    fn get_dst_opr_itf(&mut self, index: usize) -> &mut dyn OperandItf {
        &mut self.dst_oprs[index]
    }

    fn get_id(&self) -> u64 {
        self.id
    }

    fn is_ready_to_execute(&self) -> bool {
        let mut ready: bool = true;
        ready &= Self::check_ready(&self.src_oprs);
        ready &= Self::check_ready(&self.dst_oprs);
        ready
    }

    fn execute(&mut self) {
        // Placeholder for execution logic
    }
}