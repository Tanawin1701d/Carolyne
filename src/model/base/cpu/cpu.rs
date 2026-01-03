use std::rc::Rc;
use std::cell::RefCell;

use crate::simMng::eventQueue::{EventQueue, EventQueueRef};
use crate::model::base::simObject::{SimObjectRef, SimObject};
use crate::simMng::simMng::SimMng;

pub struct Cpu {
    name: String,
    cycles: u64,
}

impl Cpu{
    pub fn new(name: &str) -> Self{
        Self{
            name:name.to_string(),
            cycles:0}

    }
}

impl SimObject for Cpu{
    
    fn get_name(&self) -> &str {&self.name}
    fn tick(&mut self, eq: &mut EventQueue, self_rc: Rc<RefCell<Self>>) {
        self.cycles += 1;
        println!("{} tick {} @ {}", self.name, self.cycles, eq.now);

        eq.schedule(1, move |q| {
            self_rc.borrow_mut().tick(q, self_rc.clone());
        });
    }
    
}

impl SimObjectRef for Rc<RefCell<Cpu>>{
    fn init(&mut self, eq: &mut EventQueue) {
        let cpu = self.clone();
        eq.schedule(1, move |q| {
            cpu.borrow_mut().tick(q, cpu.clone());
        });
    }
}