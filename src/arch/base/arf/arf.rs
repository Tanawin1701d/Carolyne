//// ARF: Architectural Register File
//// N: Number of registers
//// T: Type of the registers (u32, u64, u128, f32)

////// lock the template type to be only 4 types
pub trait ARable: Default + Copy{}
impl ARable for u32{}
impl ARable for u64{}
impl ARable for u128{}
impl ARable for f32{}

pub struct Arf<const N: usize, T>{
    regs: [T; N],
}

impl<const N: usize, T: ARable> Arf<N, T>{

    pub fn new() -> Self{
        Self{
            regs: [T::default(); N],
        }
    }

    pub fn read(&self, index: usize) -> T{
        self.regs[index]
    }

    pub fn write(&mut self, index: usize, value: T){
        self.regs[index] = value;
    }

}