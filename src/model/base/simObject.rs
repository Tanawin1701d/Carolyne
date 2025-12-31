

use crate::simMng::eventQueue::{EventQueue, EventQueueRef};

pub trait SimObject{

    ////// retrieve name of the object
    fn name(&self) -> &str;

    fn init(&mut self, eq: &mut EventQueue);

}