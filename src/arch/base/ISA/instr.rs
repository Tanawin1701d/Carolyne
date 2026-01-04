use crate::arch::base::arf::arf::InstrWidth;

pub struct IsaOperand<T: InstrWidth>{
    valid    : bool,
    index    : usize,
    arfIndex : usize,
    data     : T
}

pub struct ISAUop<S0T: InstrWidth, S1T: InstrWidth,
                      D0T: InstrWidth, D1T: InstrWidth>{
    ///////// meta-data
    id   : u64,
    MopId: u64,
    opcode: u32, 
    ///////// operand
    s0: IsaOperand<S0T>,
    s1: IsaOperand<S1T>,
    d0: IsaOperand<D0T>,
    d1: IsaOperand<D1T>,
    
    
    

}

pub struct ISAMop<const MAX_AMT_MICRO_OPS: usize,
                      S0T: InstrWidth, S1T: InstrWidth,
                      D0T: InstrWidth, D1T: InstrWidth>{
    id       : u64,
    pc       : u64,
    amt_uop  : u8,
    uops: [ISAUop<S0T, S1T, D0T, D1T>; MAX_AMT_MICRO_OPS]
    
}

impl<const MAX_AMT_MICRO_OPS: usize, S0T, S1T, D0T, D1T> ISAMop<MAX_AMT_MICRO_OPS, S0T, S1T, D0T, D1T>
where
    S0T: InstrWidth,
    S1T: InstrWidth,
    D0T: InstrWidth,
    D1T: InstrWidth,
{
    pub fn new(id: u64, pc: u64) -> Self {
        Self {
            id,
            pc,
            amt_uop: 0,
            // Initializes the array using the Default implementation of ISAUop
            uops: [ISAUop::default(); MAX_AMT_MICRO_OPS],
        }
    }
}



pub trait ISAOperable{
    fn execute_next(&self, id :u64) -> u64;

    fn get(&self) -> u64;

    fn memory_read_back(&self,
                        addr: u64,
                        data: u64);
}