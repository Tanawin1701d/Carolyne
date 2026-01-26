//// ARF: Architectural Register File
//// N: Number of registers
//// T: Type of the registers (u32, u64, u128, f32)

////// lock the template type to be only 4 types
pub trait DataWidth: Default + Copy{}
impl DataWidth for u32{}
impl DataWidth for u64{}
impl DataWidth for u128{}
impl DataWidth for f32{}

pub struct Arf<const N: usize, T>{
    regs: [T; N],
}

impl<const N: usize, T: DataWidth> Arf<N, T>{

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