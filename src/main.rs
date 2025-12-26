mod simMng;
mod model;
mod arch;

use simMng::eventQueue::EventQueue;

fn main() {
    let mut eq = EventQueue::new();

    eq.schedule(10, || {
        println!("Event at t=10");
    });

    eq.schedule(5, || {
        println!("Event at t=5");
    });

    eq.run();
}
