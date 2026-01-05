use crate::arch::base::arf::arf::InstrWidth;

#[derive(Default, Copy, Clone)]

// pub struct IsaOperand<T: InstrWidth>{
//     index    : usize,
//     arfIndex : usize,
//     data     : T
// }
//
// #[derive(Default, Copy, Clone)]
// pub struct ISAUop<S0T: InstrWidth, S1T: InstrWidth,
//                   D0T: InstrWidth, D1T: InstrWidth>{
//     ///////// meta-data
//     id   : u64,
//     mop_id: u64,
//     opcode: u32,
//     ///////// operand
//     s0: IsaOperand<S0T>,
//     s1: IsaOperand<S1T>,
//     d0: IsaOperand<D0T>,
//     d1: IsaOperand<D1T>,
//
// }
//
// #[derive(Default, Copy, Clone)]
// pub struct ISAMop<const MAX_AMT_MICRO_OPS: usize,
//                       S0T: InstrWidth, S1T: InstrWidth,
//                       D0T: InstrWidth, D1T: InstrWidth>
// where
//     ISAUop<S0T, S1T, D0T, D1T>: Default + Copy,
// {
//     id       : u64,
//     pc       : u64,
//     amt_uop  : u8,
//     uops: [ISAUop<S0T, S1T, D0T, D1T>; MAX_AMT_MICRO_OPS]
//
// }
//
// impl<const N: usize, S0T, S1T, D0T, D1T> Default
// for ISAMop<N, S0T, S1T, D0T, D1T>
// where
//     S0T: InstrWidth,
//     S1T: InstrWidth,
//     D0T: InstrWidth,
//     D1T: InstrWidth,
//     ISAUop<S0T, S1T, D0T, D1T>: Default + Copy,
// {
//     fn default() -> Self {
//         Self {
//             id: 0,
//             pc: 0,
//             amt_uop: 0,
//             uops: std::array::from_fn(|_| ISAUop::default()),
//         }
//     }
// }

pub trait OperandItf {
    fn is_valid(&self) -> bool;
    fn get_index(&self) -> usize;
    fn get_arf_index(&self) -> usize;
}

pub trait UopItf{

    type Operand: OperandItf; /// it have to inherit OperandItf not only OperandItf

    fn get_amt_src_opr(&self) -> usize;
    fn get_src_opr_itf(&self, index: usize) -> &mut Self::Operand;

    fn get_amt_dst_opr(&self) -> usize;
    fn get_dst_opr_itf(&self, index: usize) -> &mut Self::Operand;

    fn get_id(&self) -> u64;

}

pub trait ISAOperable{
    fn execute_next(&self, id :u64) -> u64;

    fn get(&self) -> u64;

    fn memory_read_back(&self,
                        addr: u64,
                        data: u64);
}