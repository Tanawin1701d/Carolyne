use std::cell::RefCell;
use std::rc::Rc;
mod simMng;
mod model;
mod arch;

use simMng::eventQueue::EventQueue;
use model::base::cpu::cpu::Cpu;
use crate::model::base::simObject::SimObject;

fn main() {

    let eq = Rc::new(RefCell::new(EventQueue::new()));
    let mut cpu = Cpu::new("cpu1");


    cpu.init(Rc::clone(&eq));
    eq.borrow_mut().run();


    // let mut eq = EventQueue::new();
    //
    // eq.schedule(10, || {
    //     println!("Event at t=10");
    // });
    //
    // eq.schedule(5, || {
    //     println!("Event at t=5");
    // });
    //
    // eq.run();
}
