
use crate::simMng::eventQueue::{EventQueueRef};
use crate::model::base::simObject::SimObject;


pub struct Cpu {
    name: String,
    cycles: u64,
}

impl Cpu{
    pub fn new(name: &str) -> Self{
        Self{
            name:name.to_string(),
            cycles:0}

    }
}

impl SimObject for Cpu{

    fn name(&self) -> &str{
        &self.name
    }

    fn init(&mut self, eq: EventQueueRef){
        let name = self. name.clone();
        let eq_clone = eq.clone();

        eq.borrow_mut().schedule(1, move || {
            println!("{} tick @ {}", name, eq_clone.borrow().now);
        })
    }

}