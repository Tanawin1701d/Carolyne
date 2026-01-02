

use crate::simMng::eventQueue::{EventQueue, EventQueueRef};

pub trait SimObject{

    ////// retrieve name of the object
    fn name(&self) -> String;

    fn init(&mut self, eq: &mut EventQueue);

}