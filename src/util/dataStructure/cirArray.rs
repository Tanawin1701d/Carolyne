/// Circular Array (Ring Buffer) implementation with fixed capacity
/// Provides O(1) push/pop operations at both ends with automatic wrapping
pub struct CircularArray<T: Copy + Default, const N: usize> {
    data: [T; N],
    head: usize,  // Points to the first element
    tail: usize,  // Points to the next insertion position
    size: usize,  // Current number of elements
}

impl<T: Copy + Default, const N: usize> CircularArray<T, N> {
    /// Creates a new empty circular array
    pub fn new() -> Self {
        Self::new()
    }

    fn default() -> Self {
        Self {
            data: [T::default(); N],
            head: 0,
            tail: 0,
            size: 0,
        }
    }

    /// Returns the number of elements currently in the array
    pub fn len(&self) -> usize {
        self.size
    }

    /// Returns true if the array is empty
    pub fn is_empty(&self) -> bool {
        self.size == 0
    }

    /// Returns true if the array is full
    pub fn is_full(&self) -> bool {
        self.size == N
    }

    /// Returns the maximum capacity
    pub fn capacity(&self) -> usize {
        N
    }

    /// Pushes an element to the back of the array
    /// Returns None if the array is full
    pub fn push_back(&mut self, value: T) -> usize {
        assert!(!self.is_full());
        self.data[self.tail] = value;
        let store_id : usize = self.tail;
        self.tail = (self.tail + 1) % N;
        self.size += 1;
        store_id
    }

    /// Pops an element from the back of the array
    /// Returns None if the array is empty
    pub fn pop_back(&mut self) -> Option<T> {
        if self.is_empty() {
            return None;
        }
        self.tail = (self.tail + N - 1) % N;
        self.size -= 1;
        Some(self.data[self.tail])
    }

    /// Pushes an element to the front of the array
    /// Returns None if the array is full
    pub fn push_front(&mut self, value: T) -> usize {
        assert!(!self.is_full());
        self.head = (self.head + N - 1) % N;
        self.data[self.head] = value;
        self.size += 1;
        self.head
    }

    /// Pops an element from the front of the array
    /// Returns None if the array is empty
    pub fn pop_front(&mut self) -> Option<T> {
        if self.is_empty() {
            return None;
        }
        let value = self.data[self.head];
        self.head = (self.head + 1) % N;
        self.size -= 1;
        Some(value)
    }

    /// Returns a reference to the element at the front
    /// Returns None if the array is empty
    pub fn front(&self) -> Option<&T> {
        if self.is_empty() {
            None
        } else {
            Some(&self.data[self.head])
        }
    }

    /// Returns a reference to the element at the back
    /// Returns None if the array is empty
    pub fn back(&self) -> Option<&T> {
        if self.is_empty() {
            None
        } else {
            let back_idx = (self.tail + N - 1) % N;
            Some(&self.data[back_idx])
        }
    }

    /// Gets element at logical index (0 = front, len-1 = back)
    /// Returns None if index is out of bounds
    pub fn get(&self, index: usize) -> Option<&T> {
        if index >= self.size {
            return None;
        }
        let physical_idx = (self.head + index) % N;
        Some(&self.data[physical_idx])
    }

    pub fn borrow_by_id(&mut self, phy_id: usize) -> &mut T {
        assert!(!self.is_empty());
        assert!(self.head  < self.tail && (phy_id >= self.head && phy_id < self.tail) ||
                self.head >= self.tail && (phy_id >= self.head || phy_id < self.tail));
        &mut self.data[phy_id]
    }


    // /// Sets element at logical index (0 = front, len-1 = back)
    // /// Returns None if index is out of bounds
    // pub fn set(&mut self, index: usize, value: T) -> Option<()> {
    //     if index >= self.size {
    //         return None;
    //     }
    //     let physical_idx = (self.head + index) % N;
    //     self.data[physical_idx] = value;
    //     Some(())
    // }

    /// Clears the circular array
    pub fn clear(&mut self) {
        self.head = 0;
        self.tail = 0;
        self.size = 0;
    }
}
