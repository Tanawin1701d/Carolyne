
use std::collections::BinaryHeap;
use crate::simMng::event::{Event, Tick};
pub struct EventQueue{
    now  : Tick,
    queue: BinaryHeap<Event>,
}

impl EventQueue{

    pub fn new() -> Self{
        Self{now:0, queue: BinaryHeap::new(), }
    }

    pub fn schedule<F>(&mut self, time: Tick, callback: F)
    where
        F: FnMut() + 'static,
    {
        self.queue.push(Event {
            time,
            callback: Box::new(callback),
        });
    }

    pub fn run(&mut self) {
        while let Some(mut event) = self.queue.pop() {
            self.now = event.time;
            (event.callback)();
        }
    }
}