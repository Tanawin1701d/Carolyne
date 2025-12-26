## Project Idea: Computer Architecture Simulation Framework in Rust

I am experimenting with building a **system-level simulation framework** using **Rust**.  

### Motivation
The primary goal of this project is **personal learning**:
- Gain practical experience with Rust
- Learn how Rust can be applied to large, modular computer architecture simulators
- Explore safe and expressive abstractions for performance-critical code
- Inspired by **GEM5** and other high-performance simulators

### Scope (first stage)

- Build single Out-of-Order CORE CPU with **customizable ISA**
- Separate ARCH from MICRO-ARCH
- Support multiple ISA (RISC-V, x86, ARM, etc.)
- Implement basic memory hierarchy (cache, DRAM)

### project structure Idea

```aiignore

├── Cargo.lock
├── Cargo.toml
├── README.md
├── src
     ├── arch   # ISA sim (functional only)
     │     └── mod.rs
     ├── main.rs
     ├── model # Timing model such as O3, memCtrl, cache, GPU, etc.
     │     └── mod.rs
     └── simMng # simulation orchestrator
           ├── eventQueue.rs
           ├── event.rs
           └── mod.rs

```


