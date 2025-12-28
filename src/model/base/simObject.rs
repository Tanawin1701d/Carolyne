

use crate::simMng::eventQueue::{EventQueueRef};


pub trait SimObject{

    ////// retrieve name of the object
    fn name(&self) -> &str;

    fn init(&mut self, eq: EventQueueRef);

}