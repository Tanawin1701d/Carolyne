mod simMng;
mod model;
mod arch;

use std::rc::Rc;
use std::cell::RefCell;


use simMng::simMng::SimMng;
use model::base::cpu::cpu::Cpu;
use crate::model::base::simObject::SimObject;

fn main() {

    let mut simMng = SimMng::new();


    let cpu = Rc::new(RefCell::new(Cpu::new("cpu")));

    // need a mutable Rc binding
    let mut cpu_handle = cpu.clone();
    cpu_handle.init(&mut simMng.eq);




    // let mut cpu = Cpu::new("cpu");
    // cpu.init(&mut simMng.eq);


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
