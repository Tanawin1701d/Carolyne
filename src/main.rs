use std::cell::RefCell;
use std::rc::Rc;
mod simMng;
mod model;
mod arch;

use simMng::eventQueue::EventQueue;
use simMng::simMng::SimMng;
use model::base::cpu::cpu::Cpu;
use crate::model::base::simObject::SimObject;

fn main() {

    let mut simMng = SimMng::new();


    let mut cpu = Cpu::new("cpu");
    cpu.init(&mut simMng.eq);


    simMng.run();
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
