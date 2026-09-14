---
peer_name    : Kathryn2
peer_path    : /media/tanawin/tanawin1701e/project8/Kathryn2
peer_guide   : CLAUDE.md
my_role      : consumer
peer_role    : foundation
runtime_link : .venv/.../site-packages/kathryn.pth -> Kathryn2/py  (python side is live)
rebuild      : .venv/bin/pip install -e ../Kathryn2
rebuild_when : peer touched src/**.rs
my_test      : .venv/bin/pytest tests -q
peer_test    : cargo build && PYTHONPATH=py pytest py/tests
---

## Runtime link

`kathryn.pth` points straight at `Kathryn2/py`, so **Python-side Kathryn changes
need no rebuild** — this venv sees them at the next import. Only Rust changes
under `Kathryn2/src/` require the rebuild above.

If `pip install -e` drives maturin into a refusal (it refuses when both
`VIRTUAL_ENV` and `CONDA_PREFIX` are set), run from this project root:

```
env -u CONDA_PREFIX VIRTUAL_ENV=$PWD/.venv .venv/bin/maturin develop
```

## Placement rules

Sections of `Kathryn2/CLAUDE.md` that govern where lifted code lands:

- §1 Architectural patterns — ModelArena, the Ident handle pattern, arena factories
- §3 Naming conventions — including the `_i` suffix for ident variables
- §5 Backends — anything that emits Verilog
- §6 Code style
- §7 Python bindings — what is PyO3-gated and what is plain Python under `py/`

The Rust/Python split decides the rebuild: `py/` is live, `src/` is not.

## Do not lift

Carolyne's domain concepts. Kathryn is ISA-agnostic and CPU-agnostic; code that
names any of these is not generic and stays here:

- µop records, the µop contract, µop kinds
- ISA description types, `FieldRef`, per-ISA packages, immediate encoders
- rename, ROB, reservation station, PRF, commit, dispatch — the OoO engine itself
- the elaboration-plane / hardware-plane distinction

Precedent for what DOES belong down there: the observe and view tooling moved to
Kathryn on 2026-09-11 — generic recording and rendering, no CPU concept in it.
