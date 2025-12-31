
pub type Tick = u64;


use std::cmp::Ordering;
use crate::simMng::eventQueue::EventQueue;

pub struct Event{
    pub time: Tick,
    pub callback: Box<dyn FnMut(&mut EventQueue)>,
}

impl Ord for Event{

    fn cmp(&self, other: &Self) -> Ordering {
        //// we do want min heap; therefore, comparator have to be reverse
        other.time.cmp(&self.time)
    }

}

impl PartialOrd for Event{
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl PartialEq for Event {
    fn eq(&self, other: &Self) -> bool {
        self.time == other.time
    }
}

impl Eq for Event {}