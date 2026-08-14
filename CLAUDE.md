# Carolyne — Contributor Guide for AI Agents

Auto-loaded by Claude Code at session start. Read before making changes.

## 1. What Carolyne is

An **ISA-agnostic out-of-order CPU generator**, written in Python on top of
the **Kathryn** hardware-construction library (sibling repo
`../Kathryn2`: Rust core, Python DSL via PyO3, Verilog backend).

Two research aspects, in priority order:

1. **ISA / microarchitecture separation** (the novelty claim). The OoO engine
   is written once against a fixed *µop contract*; an ISA is supplied as a
   small description package. The engine **adapts itself at elaboration
   time** — rename tables, decoder trees, PRFs, commit logic are derived from
   the description, never hand-written per ISA. Niche: ISA researchers get a
   synthesizable OoO implementation without building a microarchitecture.
2. The generated core as a **reconfigurable component** that drops into a
   larger Kathryn design (engineering, not the headline).

Publication target: conference paper demonstrating one shared engine with
**RV32I + a precisely scoped mini-x86**, reporting IPC / FPGA area / fmax and
an effort metric (lines of ISA description vs lines of shared engine).
Positioning vs prior art: gem5 (ISA/µarch split, simulation only), FabScalar
(OoO RTL, one fixed ISA), BOOM (RISC-V only), LISA/nML ADL flows (RTL, but
in-order only).

## 2. The load-bearing concept: two planes

- **Elaboration plane** (everything in `carolyne/isa/`): pure TEMPLATE,
  consumed at generate time. **No runtime value ever lives in the ISA
  layer** — it holds *rules* for how hardware obtains values at runtime
  (e.g. `FieldRef("rd")` = "index arrives from the decoder's field
  extractor"). No Kathryn imports anywhere in `carolyne/isa/`.
- **Hardware plane** (run time): after decode the front-end and engine speak
  exclusively in **µop records**. Rule: no raw ISA bits ride along in the
  record — if that happens, the separation is dead.

Normative spec: `docs/design/uop_contract.md` (µop kind catalog is owned by
the contract with a CustomFu escape hatch; `ilen()` is the only
variable-length mechanism; first/last bounds give instruction-granular
commit; "x86 FLAGS needs zero special-casing in uarch" is the litmus test;
§6 lists the five deliverables a new ISA supplies; §8 has open questions
Q1–Q4). If bringing up an ISA forces an edit inside `uarch`, that is a
contract bug — fix the contract, not the engine.

## 3. Layout and dependency rules

| path                          | contents                                              |
| ----------------------------- | ----------------------------------------------------- |
| `docs/design/uop_contract.md` | normative ISA↔µarch boundary spec                     |
| `carolyne/isa/`               | description types + per-ISA packages (riscv, x86mini) |
| `carolyne/contract/`          | placeholder for the µop-record side (not built yet)   |
| `carolyne/uarch/`             | generic OoO engine, Kathryn code lives here           |
| `examples/regfile_demo.py`    | smallest end-to-end Kathryn flow (CPU-flavored)       |
| `generated/`                  | emitted Verilog (gitignored)                          |
| `tests/`                      | pytest; tests double as usage documentation           |

Rules: `isa` never imports `uarch` or `kathryn`. `uarch` may import the
description types but must never name a specific ISA. Per-ISA packages
contain description data only — no hardware code.

## 4. What exists so far (`carolyne/isa/`)

- **`RegFile(name, width, amount, renamed=True, const_regs={})`** — metadata
  for one architectural register class. Decision: store `amount` (count),
  *derive* `index_width` (`(amount-1).bit_length()`), so PRF sizing (count)
  and µop index fields (log2) can never disagree; a 1-reg file (x86 FLAGS)
  derives index width 0. `const_regs` maps arch idx → hardwired value
  (RISC-V `{0: 0}`); rename bypasses reads, discards writes. Flags/GPRs/
  anything are all "just register classes" to the engine.
- **`Intermediate(width, name="")`** — µtemp: intra-instruction value between
  µops of one cracked instruction, dead at the instruction boundary.
  Decision: `eq=False` — every instance is a distinct value node; a cracker
  links µops by *reusing the instance* (x86 `add [m],r`: AGU→addr,
  LOAD addr→old, ADD old→new, STORE new). The elaborator assigns temp
  indices; the description layer never numbers them.
- **`FieldRef(name)`** — index *rule*: "register number comes from this
  encoding field at runtime". Name-only for now; bit positions and existence
  are validated when crackers get bound to the encoding table (not built yet).
- **`Operand(target, index=None)`** — one src/dest slot of a µop template.
  Target is a `RegFile` (index rule required: `FieldRef` = decoded register,
  literal `int` = implicit register — x86 push/pop→ESP, flags writes; both
  elaborate to the same rename port, constant vs extractor wiring) or an
  `Intermediate` (index forbidden — the instance is the link). `is_const` is
  true only for a literal index onto a hardwired reg; a decoded index hitting
  x0 is rename's runtime job.

Immediates are deliberately NOT an `Operand` target — the µop record carries
`imm` as its own field (contract §2).

- **`Op(name)`** — one operation kind, a first-class object rather than a
  bare string (still not an enum: a custom-FU op must be as first-class as
  `ADD`). Decision: **standalone**, not owned by a unit — the same `Op` may
  sit in several `ExecUnit`s. Value equality on the name (`Op("ADD") ==
  Op("ADD")`), so two description files naming the same op build µops that
  match; identity semantics stay with `Intermediate`. v0.1 carries the name
  only — the object exists so latency/arity/FU hooks have a home when a
  consumer needs them.
- **`ExecUnit(name, ops)`** — one execution-unit class; `ops` is a frozenset
  of `Op`s (non-`Op` members raise, never promoted from strings — a stray
  `"ADD"` would compare unequal to everyone else's `Op("ADD")`).
  `unit.op("ADD")` is the one sanctioned text→`Op` door, for encoding-table
  rows. Latency/ports deferred until the issue-port design consumes them.
- **No catalog ships in code.** The §1.2 op/unit table is spec text; every
  ISA/machine declares its own `Op`s and `ExecUnit`s (see the header block
  of `tests/test_uop.py`). Reason: importable `ALU`/`ADD` constants would
  make the natives privileged over an op a custom FU declares — the exact
  distinction this layer refuses to make — and nothing consumes such a list
  yet. `STANDARD_UNITS`/`STANDARD_OPS` existed briefly on 2026-08-14 and
  were deleted; don't restore them from git.
- **`Uop(op, srcs, dests, imm)`** — one µop template. Decision: the template
  names **only its `Op`**, no unit — which FU executes a kind is a machine
  configuration question answered by the unit set (`ExecUnit.ops` read the
  other way round), and an op two units both list is a routing choice, not
  an error. Cost of dropping `unit`: a bogus op survives construction — it is
  `IsaDescription` that refuses it. Operand
  counts are capped at the record shape (≤3 src, ≤2 dest, §2). `imm` is `int`
  (cracker-baked constant, x86 push→ESP−4) or `FieldRef` (extracted field).
  No first/last bound on the type — that comes from position in the cracker
  sequence (later); mem/br sub-fields deferred until FU semantics land. An
  instruction family sharing one shape is a factory function in the per-ISA
  package, not a multi-op field (a multi-op `ops` was tried and reverted: the
  record carries exactly one `kind`, so a family would be an unbound template
  every consumer must handle).

- **`InstrFieldMatch(name, match_idx)` / `UopSeq(uops, matcher)` /
  `Mop(matcher, uop_seq)`** (`mop.py`) — the encoding side, still
  preliminary: a match rule is a named set of `(start, end)` bit segments,
  end-exclusive. Every `matcher` field (here, and on `Operand`/`Uop`) holds
  **one** `InstrFieldMatch` or `None`, not a tuple. `Mop` requires its
  matcher; the rest default to `None`.
- **`IsaDescription(name, ops, exec_units, mops)`** (`isa.py`) — the whole
  ISA, the object a generator is handed. Decision: `ops` is **declared, not
  derived** from the mops or units — deriving would make a typo
  self-consistent. It cross-checks at construction: every op a mop's µops
  name must be declared, and every declared op must be executable by ≥1 unit;
  the reverse (a unit listing ops this ISA never uses) is allowed so unit
  definitions can be shared. Names unique per vocabulary. Lookups: `op(name)`,
  `unit(name)`, `units_for(op)` (the kind→FU map read out), `used_ops()`.
  Reg files / ilen / trap policy join it when those types exist.

A first `Layout`/`Mop` pair (encoding metadata + macro-op variants binding an
encoding to a µop sequence) was written and then removed as sloppy, and the
current `mop.py` is the from-scratch redesign — the encoding side of the
contract (§1.3) is still open; don't restore the old one from git.

Agreed next steps: give `UopSeq` the cracker-sequence duties it still lacks
(stamp first/last, validate µtemp def-before-use), settle how a matcher binds
`FieldRef`s to bit segments, and add the remaining §6 deliverables to
`IsaDescription` (reg files, ilen, trap policy); alternatively first Kathryn
RAT/PRF elaboration from a `RegFile` in `uarch`.

## 5. Environment & workflow

- Venv at `.venv/` (Python 3.13). `kathryn` is an **editable install from
  `../Kathryn2`** (pip drove maturin). After Rust-side Kathryn changes:
  re-run `pip install -e ../Kathryn2` (or `maturin develop` there);
  Python-side DSL changes are picked up automatically.
- `pip install -e ".[dev]"` for carolyne + pytest. Run tests:
  `.venv/bin/pytest tests -q`. Run the demo:
  `.venv/bin/python examples/regfile_demo.py`.
- User's IDE is **PyCharm** (interpreter pointed at `.venv/bin/python`).
  RustRover leftovers were removed; `.idea/` stays gitignored.
- PyCharm may flag imports of freshly created files as unresolved — indexer
  lag, trust the pytest run.

## 6. Kathryn facts this project leans on

- `Module` subclass, `@init` (declare hw, runs eagerly) / `@flow` (deferred
  until `gen_flow`). Build pipeline: `reset()` → `set_top(mod())` →
  `gen_flow()` → `build_flow()` → `emit_verilog(dir, name)`.
- **`emit_verilog` CONSUMES the singleton arena** — one emit per
  reset/rebuild cycle.
- Assign operators carry intent: `|=` clocked (reg), `*=` combinational
  (wire); bare `=` is rejected. Conditional blocks (`sif` etc.) hold
  sub-blocks, not direct nodes — nest a `seq()` inside.
- `Karray` is the RAT/PRF primitive: reg/wire-backed multi-dim arrays of
  named fields; `arr[sig]` dynamic index → generated write guards per
  element / mux trees on read; callable index → one-hot writes or reduce
  trees; k2k assigns pair fields structurally. clk/mrst wiring is automatic
  in `build_flow`.

## 7. Conventions

- Discuss design decisions before coding them; when a choice is made, record
  the *why* in the file's header comment.
- Validate descriptions at construction (`__post_init__` raising ValueError
  with the reg-file/operand name in the message) so bad ISA specs fail
  loudly, not deep in elaboration.
- Tests double as usage documentation — e.g. `tests/test_operand.py` builds
  the x86 `add [mem], reg` cracking shape from the contract doc.
- Description types are frozen dataclasses, pure data, no Kathryn imports.
