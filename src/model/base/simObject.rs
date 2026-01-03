use std::cell::RefCell;
use std::rc::Rc;
use crate::simMng::eventQueue::{EventQueue, EventQueueRef};

pub trait SimObjectRef {

    fn init(&mut self, eq: &mut EventQueue);

}

pub trait SimObject{

    fn get_name(&self) -> &str;
    
    fn tick(&mut self, eq: &mut EventQueue, self_rc: Rc<RefCell<Self>>)
        where Self: Sized;

}



#[derive(Debug, PartialEq, Clone, Copy)]
pub enum SimState{
    Created,
    Running,
    Paused,
    Finished,
}