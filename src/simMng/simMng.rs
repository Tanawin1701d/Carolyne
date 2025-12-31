use crate::simMng::eventQueue::EventQueue;

pub struct SimMng{
    pub eq: EventQueue
}

impl SimMng{

    pub fn new() -> Self{
        Self{eq:EventQueue::new()}
    }

    pub fn run(&mut self) {
        while let Some(mut event) = self.eq.pop() {
            self.eq.now = event.time;
            (event.callback)(&mut self.eq);
        }
    }


}