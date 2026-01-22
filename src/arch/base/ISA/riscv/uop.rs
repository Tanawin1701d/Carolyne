use crate::arch::base::ISA::base_opr::{OperandItf};
use crate::arch::base::ISA::base_uop::{UopItf, NEXT_UOP_ID};
use crate::arch::base::ISA::riscv::opr::{RiscvOperand, RISCV_MAX_NUM_SRC_OPRS, RISCV_MAX_NUM_DST_OPRS};

pub const RISCV_MAX_NUM_UOPS: usize = 2;

#[derive(Copy, Clone)]
pub struct RiscvUop {
    id          : u64,
    src_oprs    : [RiscvOperand; RISCV_MAX_NUM_SRC_OPRS],
    dst_oprs    : [RiscvOperand; RISCV_MAX_NUM_DST_OPRS],
    opcode      : u32,
    sub_opcode  : u32,
    imm         : u32,
    src_opr_cnt : usize,
    dest_opr_cnt: usize,
}

impl RiscvUop {

    pub fn new() -> Self{
        let new_item = Self::default();
        new_item
    }
    pub fn default() -> Self{
        RiscvUop {
            id          : 0,
            src_oprs    : [RiscvOperand::default(); RISCV_MAX_NUM_SRC_OPRS],
            dst_oprs    : [RiscvOperand::default(); RISCV_MAX_NUM_DST_OPRS],
            opcode      : 0,
            sub_opcode  : 0,
            imm         : 0,
            src_opr_cnt : 0,
            dest_opr_cnt: 0,
        }
    }
    
    pub fn add_src_opr(&mut self, opr: RiscvOperand) {
        assert!(self.src_opr_cnt < RISCV_MAX_NUM_SRC_OPRS,
                "Source operand count overflow (RiscvUop)");
        self.src_oprs[self.src_opr_cnt] = opr;
        self.src_opr_cnt += 1;
    }

    pub fn add_dst_opr(&mut self, opr: RiscvOperand){
        assert!(self.dest_opr_cnt < RISCV_MAX_NUM_DST_OPRS,
                "Destination operand count overflow (RiscvUop)");
        self.dst_oprs[self.dest_opr_cnt] = opr;
        self.dest_opr_cnt += 1;
    }

    pub fn set_opcode    (&mut self, opcode: u32) { self.opcode = opcode; }
    pub fn set_sub_opcode(&mut self, sub_opcode: u32) { self.sub_opcode = sub_opcode; }
    pub fn set_imm       (&mut self, imm: u32) { self.imm = imm; }

    fn check_ready(oprs: &[RiscvOperand], amt: usize) -> bool {
        
        for opr_idx in 0..amt {
            if !oprs[opr_idx].is_valid() {
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
    fn assign_id(&mut self) {
        self.id = NEXT_UOP_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    }

    fn is_ready_to_execute(&self) -> bool {
        let mut ready: bool = true;
        ready &= Self::check_ready(&self.src_oprs, self.src_opr_cnt);
        ready &= Self::check_ready(&self.dst_oprs, self.dest_opr_cnt);
        ready
    }

    fn execute(&mut self) {
        // Placeholder for execution logic
    }
}