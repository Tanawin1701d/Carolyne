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

| path                          | contents                                                        |
| ----------------------------- | --------------------------------------------------------------- |
| `docs/design/uop_contract.md` | **the normative spec** of the ISA ↔ µarch boundary              |
| `carolyne/isa/`               | description types + `ExecUnitApi` + per-ISA packages (`riscv/`) |
| `carolyne/uarch/`             | the generic OoO engine, built from Kathryn primitives           |
| `examples/regfile_demo.py`    | smallest end-to-end Kathryn flow (CPU-flavored)                 |
| `generated/`                  | emitted Verilog (gitignored)                                    |
| `tests/`                      | pytest suite; tests double as usage documentation               |

Dependency rules: `isa` never imports `uarch`; its description TYPES never
import `kathryn` (a package's semantics modules — `exec_stage` bodies — may).
`uarch` may import the description types but never names a specific ISA.
There is no `contract` package: the boundary is a DOCUMENT, and the one
interface it needs in code (`ExecUnitApi`) lives in `isa/`, because the ISA
layer is who writes stage bodies against it.

## Setup

One-time, from this repo's root (fresh machine / fresh venv):

```bash
# 1. create the venv
python3.13 -m venv .venv
source .venv/bin/activate

# 2. install Carolyne + pytest
pip install -e ".[dev]"

# 3. install Kathryn (sibling repo, not on PyPI) — editable; pip drives maturin
pip install -e ../Kathryn2

# 4. run tests
pytest tests -q

# 5. run the demo — a 4-entry register file + accumulator, emitted to generated/
python examples/regfile_demo.py
```

## Updating Kathryn

The editable install is a `.pth` link straight into `../Kathryn2/py/`, so what
you must do after pulling or editing Kathryn depends on WHICH half changed:

| what changed                               | what to do                               |
| ------------------------------------------ | ---------------------------------------- |
| Python side (`Kathryn2/py/kathryn/`)       | nothing — imports pick it up immediately |
| Rust side (`Kathryn2/src/`, `Cargo.toml`)  | rebuild the `.so` (one command below)    |
| `Kathryn2/pyproject.toml` (deps, name)     | re-run `pip install -e ../Kathryn2`      |

Rebuilding the `.so` — pick ONE, they end in the same place:

```bash
# day-to-day: fast debug build (venv MUST be active, or maturin targets the wrong env)
cd ../Kathryn2 && maturin develop

# rare: redo the whole editable install (fresh machine, broken venv, metadata change)
.venv/bin/pip install -e ../Kathryn2
```

- Debug vs release only changes ELABORATION speed (Python calling into Rust);
  the emitted Verilog is identical. If elaborating a big core feels slow:
  `maturin develop --release`.

Am I stale? Compare the last Rust-touching commit against the build:

```bash
git -C ../Kathryn2 log -1 --format='%ad' --date=iso                       # last commit
ls -l ../Kathryn2/py/kathryn/_kathryn.cpython-313-x86_64-linux-gnu.so     # build time
```

If the `.so` predates a commit that touched `src/`, rebuild. Quicker
functional check: `pytest tests -q` — a stale binary shows up as an
`ImportError` or a missing attribute on a Kathryn type.

Gotchas:

- `pip install -e` never needs re-running for ordinary upgrades — an old
  dist-info date is normal; only package METADATA changes warrant it.
- A stale untagged `_kathryn.so` beside the `cpython-313`-tagged one is
  harmless (Python prefers the tagged file) — but if a rebuild seems to
  change nothing, delete the untagged leftover.
