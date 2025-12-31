
use crate::simMng::eventQueue::{EventQueue, EventQueueRef};
use crate::model::base::simObject::SimObject;
use crate::simMng::simMng::SimMng;

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

    fn init(&mut self, eq: &mut EventQueue){
        let name = self. name.clone();

        eq.schedule(1, move |q| {
            println!("{} tick @ {}", name, q.now);
        })
    }

}