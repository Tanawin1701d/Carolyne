# Carolyne

An **ISA-agnostic out-of-order CPU generator**, written in Python on top of the
[Kathryn](../Kathryn2) hardware-construction library.

## The idea

Carolyne separates the **ISA** from the **microarchitecture**. The
out-of-order engine (fetch, rename, issue, execute, commit) is written once,
against a fixed *µop contract*; an ISA is supplied as a small Python
description package (register classes, encodings, crackers). The engine
**adapts itself at elaboration time** — rename tables, decoder trees, physical
register files, and commit logic are generated from the ISA description.

The niche: ISA researchers get a synthesizable out-of-order implementation of
a new ISA without building a microarchitecture. Existing tools each cover only
part of this — gem5 separates ISA from µarch but only in simulation; FabScalar
generates OoO RTL but for one fixed ISA; BOOM is RISC-V-only; ADL flows
(LISA/nML) generate RTL only for in-order pipelines.

Second aspect: the generated core is a **reconfigurable component** — a clean,
parameterized block (memory port + control interface) that drops into a larger
Kathryn design.

First publication target: one shared engine demonstrated with **RV32I** and a
precisely scoped **mini-x86**, reporting IPC / FPGA area / fmax for both, plus
the effort metric (lines of ISA description vs lines of shared engine).

## Layout

| path                        | contents                                                        |
| --------------------------- | --------------------------------------------------------------- |
| `docs/design/uop_contract.md` | **the normative spec** of the ISA ↔ µarch boundary            |
| `carolyne/contract/`        | Python object model of that contract (`IsaDescription`, µops)   |
| `carolyne/isa/`             | ISA packages: `riscv/`, `x86mini/` — contract deliverables only |
| `carolyne/uarch/`           | the generic OoO engine, built from Kathryn primitives           |
| `tests/`                    | pytest suite                                                    |

Dependency rule: `isa` and `uarch` never import each other; both import only
`contract`. Nothing in `uarch` may name a specific ISA.

## Setup

```bash
# 1. install Kathryn (sibling repo, not on PyPI) into the same environment
pip install -e ../Kathryn2        # or: cd ../Kathryn2 && maturin develop

# 2. install Carolyne
pip install -e ".[dev]"

# 3. run tests
pytest tests

# 4. run the demo — a 4-entry register file + accumulator, emitted to generated/
python examples/regfile_demo.py
```
