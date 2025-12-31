use std::cell::RefCell;
use std::rc::Rc;
use std::collections::BinaryHeap;
use crate::simMng::event::{Event, Tick};
use crate::simMng::simMng::SimMng;

pub type EventQueueRef = Rc<RefCell<EventQueue>>;

pub struct EventQueue{
    pub now  : Tick,
    queue: BinaryHeap<Event>,
}

impl EventQueue{

    pub fn new() -> Self{
        Self{now:0, queue: BinaryHeap::new(), }
    }

    pub fn schedule<F>(&mut self, time: Tick, callback: F)
    where
        F: FnMut(&mut EventQueue) + 'static,
    {
        self.queue.push(Event {
            time,
            callback: Box::new(callback),
        });
    }
    
    pub fn is_empty(&self) -> bool{
        self.queue.is_empty()
    }
    
    pub fn peek(&self) -> Option<&Event>{
        self.queue.peek()
    }
    
    pub fn pop(&mut self) -> Option<Event>{
        self.queue.pop()
    }
    
    pub fn last_tick(&self) -> Tick{
        self.now
    }
    

    // pub fn run(&mut self) {
    //     while let Some(mut event) = self.queue.pop() {
    //         self.now = event.time;
    //         (event.callback)();
    //     }
    // }
}