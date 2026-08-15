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

- **`RegFile(name, width, amount, renamed=True, const_regs={})`** (`reg.py`) — metadata
  for one architectural register class. Decision: store `amount` (count),
  *derive* `index_width` (`(amount-1).bit_length()`), so PRF sizing (count)
  and µop index fields (log2) can never disagree; a 1-reg file (x86 FLAGS)
  derives index width 0. `const_regs` maps arch idx → hardwired value
  (RISC-V `{0: 0}`); rename bypasses reads, discards writes. Flags/GPRs/
  anything are all "just register classes" to the engine.
- **`Intermediate(width, name="")`** (`reg.py`, beside `RegFile`) — µtemp: intra-instruction value between
  µops of one cracked instruction, dead at the instruction boundary.
  Decision: `eq=False` — every instance is a distinct value node; a cracker
  links µops by *reusing the instance* (x86 `add [m],r`: AGU→addr,
  LOAD addr→old, ADD old→new, STORE new). The elaborator assigns temp
  indices; the description layer never numbers them.
- **`FieldRef(name)`** — index *rule*: "register number comes from this
  encoding field at runtime". Name-only for now; bit positions and existence
  are validated when crackers get bound to the encoding table (not built yet).
- **`AtomicOperand(role, reg_file=None, intermediate=None)`**
  (`atomic_operand.py`) — the core of an operand: the VALUES a slot may name
  and the DIRECTION it flows. Decision: **two optional target fields, not one
  `Union`** — a Union says "this slot names exactly one of these, decided
  here"; the pair says "these are the candidates, and the `Operand` decides".
  That is what lets one core serve rules that resolve differently, the shape an
  ISA needs when a single encoding slot is a register in one form and a loaded
  value in another (x86 ModRM r/m). At least one target is required. Cost, and
  it is real: a core no longer states WHICH value a slot names, only the menu,
  so the check that a slot targets what it should moved to `Operand`, where the
  selection is. `target_for(kind)` performs the selection (one place maps kind
  → field) and *raises* if the core does not carry it; `has_arch`/`has_temp`
  say what is on offer. Decision: it carries **no `width`, `is_arch`,
  `is_intermediate`** (ambiguous with two candidates — only the selection
  answers them) and **no `is_const`/`is_decoded`** (facts about the *index*,
  which the core has not got). It owns `OperandRole` (`SRC`/`DEST`) and
  `TargetKind` (`ARCH`/`TEMP`), so the import runs `operand` →
  `atomic_operand` one-way. `OperandRole` **is** an enum where `Op`
  deliberately is not — an ISA may declare an unanticipated op, but §2 gives
  the record exactly src/dest slots, so no ISA invents a third role; and there
  is **no `SRC_DEST`**, since an arch slot read *and* written through one field
  (x86 `add eax, ebx`) is two operands filling two record slots and two rename
  ports. An `amount == 1` refusal briefly lived here and was removed — it could
  not survive `Operand` holding a core, since 30 of RV32I's 37 operands target
  a 32-register file. Don't restore it from git; its useful half is `Operand`'s
  index-omission rule.
- **`Operand(atomic, target_kind, index=None, matcher=None)`** — one src/dest
  slot of a µop template: an `AtomicOperand` plus the ENCODING SIDE.
  `target_kind` is the **selector**, required and never inferred from "the core
  only has one target" — an inferred selector would change meaning silently the
  day that core grows its second. `__post_init__` resolves it immediately, so a
  rule selecting a target its core does not carry fails at construction.
  Because the selection lives here, so do `target`, `width`, `is_arch`,
  `is_intermediate`; only `role`/`is_src`/`is_dest` forward from the core. For
  a `RegFile` target the index rule is required (`FieldRef` = decoded register,
  literal `int` = implicit register — x86 push/pop→ESP; both elaborate to the
  same rename port, constant vs extractor wiring) **except on a one-register
  class**, where `index_width` is 0, there is nothing to choose, and the
  elaborator wires the single register (x86 FLAGS). An `Intermediate` target
  forbids an index — the instance is the link. `is_const` is true for a literal
  index onto a hardwired reg, or for an omitted index on a one-register class
  (that register is 0); a *decoded* index hitting x0 is rename's runtime job.
  The role living in the core is what `Uop.srcs`/`dests` cross-check against
  position, so a `DEST` in `srcs` raises. Decision: **composition, not
  inheritance** — `Operand` is not substitutable for its core, since it demands
  an index rule the core knows nothing about. Cost, accepted: every
  construction site names the core AND the selection, which per-ISA packages
  tame by sharing core constants (`riscv/operand.py` names one core per SLOT —
  `AOPR_SRC_1/2/3`, `AOPR_DEST_1`, the first two value-equal twins on purpose —
  and hangs its nine rules off them; free, since an `AtomicOperand` is frozen
  and value-equal). Decision: a `Uop` slot is an `Operand`, **never** a bare
  `AtomicOperand` and never a union of the two — a µop template always states
  its index rule, and a union would make every consumer downstream ask which
  kind it got first. A `UopOperand = Union[...]` alias existed briefly on
  2026-08-15 and was removed; don't restore it.

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
  `IsaBase` that refuses it. Operand counts are capped at the record shape
  (≤3 src, ≤2 dest, §2). `imm` is `int`
  (cracker-baked constant, x86 push→ESP−4) or `FieldRef` (extracted field).
  No first/last bound on the type — that comes from position in the cracker
  sequence (later); mem/br sub-fields deferred until FU semantics land. An
  instruction family sharing one shape is a factory function in the per-ISA
  package, not a multi-op field (a multi-op `ops` was tried and reverted: the
  record carries exactly one `kind`, so a family would be an unbound template
  every consumer must handle).

- **`InstrFieldMatch(name, match_idx)`** (`field_match.py`) — a named field
  as `(start, end)` bit segments, end-exclusive; a tuple of them because a
  field need not be contiguous. `union(*others, name=…)` (also `|`) combines
  fields into ONE rule — how add-vs-sub states funct3 **and** funct7 in a
  single `matcher` slot. It only **appends**: no sorting, no merging, no
  overlap check, because segment order and boundaries are the caller's
  statement about the field and rewriting them would rewrite the rule.
  `width` sums the bits.
- **`InstrValueMatch(match_value)`** (`field_match.py`) — the value half: what
  the bits must EQUAL, which is what makes an encoding discriminable.
  Decision: **values only, no field**. The two halves stay separate types the
  way "where a field is" and "which index reads it" already are, so a value
  rule is a bare bit pattern and whatever pairs the two states which bits it
  tests. Decision: **one value per segment** of that field, same order — not
  one assembled integer, because the type still cannot say where a scrambled
  field's segments land, so there is no layout to assemble INTO; add-vs-sub is
  then `(0b000, 0b0000000)` vs `(0b000, 0b0100000)`, reading like the spec
  table. `union`/`|` appends values and is meant to be called in step with the
  field union, in the same order, so segments and values stay index-aligned.
  Its own validation is therefore only what a bare pattern allows — non-empty,
  ints, non-negative. No `matches(word)` method — evaluating a rule is
  runtime, this layer holds rules only.
- **`check_matcher_pair(matcher_field, matcher_value, where)`**
  (`field_match.py`) — holds the two halves to each other, which neither can
  do alone: one value per segment, each narrow enough for the segment it
  tests. A field alone is legal (positions stated, nothing tested — the state
  RV32I is in); a value alone is not. Called by `Uop`, `UopSeq` and `Mop`.
  **/ `UopSeq(uops, matcher_field, matcher_value)` /
  `Mop(matcher_field, matcher_value, uop_seq)`** (`mop.py`) — the encoding
  side, still preliminary. Decision: the matcher is **TWO SLOTS**, not one
  slot typed as either — two slots is what makes the pair checkable, and
  "positions only" is then just `matcher_value=None`. `Mop` requires its
  `matcher_field`; every value slot defaults to `None`, so nothing yet
  *requires* a value and the place to demand one for a decodable ISA is
  `IsaBase`, which sees the whole table. `Operand` keeps a single `matcher`
  (`InstrFieldMatch` only): it says where an index or immediate is READ from
  and tests nothing.
- **`IsaBase(name, reg_files, ops, exec_units, mops)`** (`isa.py`) — the
  whole ISA, the object a generator is handed. Decision: `ops` and
  `reg_files` are **declared, not derived** from the mops — deriving would
  make a typo self-consistent. It cross-checks at construction: every op and
  every reg file a mop's µops use must be declared, and every declared op
  must be executable by ≥1 unit; the reverse (a unit listing unused ops, a
  declared-but-unused reg file) is allowed, so unit definitions can be shared
  and a class can be declared before a crack touches it. Reg files match by
  **identity** — one PRF per instance, and `RegFile` holds a dict so it is
  unhashable anyway. Names unique per vocabulary. Lookups: `op(name)`,
  `unit(name)`, `reg_file(name)`, `units_for(op)` (the kind→FU map read out),
  `used_ops()`, `used_reg_files()`. Named *Base* because a per-ISA package
  may subclass it for fields this container doesn't model — subclasses must
  stay `frozen=True` and stay **data**: overriding `op()`/`units_for()`/
  `__post_init__` would put ISA-specific behavior on the elaborator's path.
  `ilen` / trap policy join it when those types exist.

**`carolyne/isa/riscv/`** is the first per-ISA package, deliberately a
TEMPLATE skeleton: `reg.py` (`x_file()` → x0..x31, x0 via `const_regs`;
**PC is deliberately not a register class** — it is front-end/ROB state, not
something the engine renames through a PRF port, so a 1-entry `pc` file was
drafted and deleted), `op.py` (its own op vocabulary + `exec_units()` — no
shipped catalog), `field_match.py` (32-bit field positions, `ILEN_BYTES = 4`,
and `FORMATS` = the six base formats R/I/S/B/U/J as `union`s of those fields,
each tiling the word exactly once — declared but not yet consumed, since a
`Mop` has no format slot), `uop.py` (`UOP_*` + `UOPS`), `mop.py` (`MOP_*` +
`MOP_TABLE` → 11 opcode-group `Mop`s, exhaustive over `UOPS`), `rv32i.py`
(`rv32i()` → `IsaBase`, nothing else). The table is grouped by OPCODE, not by
format: the two are different partitions — I-type spans LOAD, OP-IMM, JALR and
SYSTEM — so a format-grouped table would need one `Mop` matching four opcode
values, which one matcher cannot say. `MOP_TABLE` is a module constant rather
than a builder function, on the same frozen-data / shared-instance terms as
the operand constants below. It builds and passes every container cross-check.
The operand rules (`OPR_RD/OPR_RS1/OPR_RS2`, and the six `OPR_IMM_*`) are
**module constants**, so the register class they target is one too:
`reg.RegFile` — a shared instance built by `x_file()`, which `rv32i()` also
declares. `IsaBase` matches reg files by identity, and sharing constants
makes those the same object by construction. Accepted cost: two `rv32i()`
builds share it; `x_file()` builds a fresh one for a caller who needs
independence. An immediate operand targets `reg.ImmTarget` (an
`Intermediate`, so it allocates no PRF) and carries **no index** — an index
answers "which register of the class", which an immediate has not got, and
`Operand.__post_init__` enforces that. Its `matcher` is the whole rule. The
`OPR_IMM_*` constants are declared but **not yet used by any shape**: `Uop`
has no `imm` field, so `rv32i.py` marks each site `# imm:` instead. Ops and field positions
stay constants — value-equal, so sharing couples nothing.
RV32I declares **no AGU**: its addressing is base+imm only, so the address is
not a value a second µop consumes and loads/stores are single µops. (x86's
read-modify-write feeds one address to both a LOAD and a STORE, so it will
declare AGU — per-ISA vocabularies make that a local choice.) Consequence:
RV32I uses no `Intermediate` at all. It also declares no `CALL_LINK`: the
jump µop writes its own link register, so **every RV32I instruction is
exactly one µop** and this ISA exercises none of the cracking machinery — no
µtemps, no first/last bounds. x86mini is what will test that side; the µtemp
mechanism is pinned meanwhile by the x86 shape in `test_uop.py`. Its KNOWN GAPS
blocks are the real output — bringing up RV32I is what surfaced them, and
each is contract-side, fixable without touching `uarch`:
`Uop` has no `imm` (so immediates ride in `srcs`, which contract §2 says they
should not); since PC is not a reg file, auipc and the jal/jalr link value have
**no way to name the instruction's own PC** as an input, and the contract needs
to say it is read from the µop record; and a matcher **discriminates but does
not extract** — nothing says where each segment of a scrambled immediate lands
in the assembled value, so a decoder can now pick the instruction and still not
build its immediate. Two former gaps are closed and *used*: `FUNCT3_7 = FUNCT3
| FUNCT7` spans both fields, and **every matcher in the package now states its
value** — `FM.val(...)` beside the field, opcode values on the eleven `Mop`
groups and funct values on the 37 templates that name a field (LUI/AUIPC/JAL
name none: their opcode alone identifies them, and that is the Mop's rule). So
add-vs-sub and ecall-vs-ebreak are genuinely distinguishable, and
`check_matcher_pair` catches a mis-sized value at import.

One gap was closed by enumerating instead of extending the record: memory
width/sign and branch condition are **distinct ops** (`LB/LH/LW/LBU/LHU`,
`SB/SH/SW`, `BEQ/BNE/BLT/BGE/BLTU/BGEU`, tuples `LOADS`/`STORES`/`BRANCHES`),
and `AUIPC` is its own op rather than an `ADD` missing its PC source. Generic
`LOAD`/`STORE`/`BR_COND` kinds would have needed record sub-fields that only
those kinds read — a second way of saying what `kind` already says. Cost: 32
ops and more cases per FU; benefit: the §2 record stays as written and the
decoder never fills a field it doesn't understand.

A first `Layout`/`Mop` pair (encoding metadata + macro-op variants binding an
encoding to a µop sequence) was written and then removed as sloppy, and the
current `mop.py` is the from-scratch redesign — the encoding side of the
contract (§1.3) is still open; don't restore the old one from git.

A `PhyOperand` (the post-rename record slot: role, slot, class, physical index
width, const-bypass value) was built in `carolyne/contract/` on 2026-08-15 and
removed the same day — the hardware-plane side stays empty until the elaborator
that consumes it exists. Don't restore it from git. What it surfaced is worth
keeping: a physical index is a run-time value, so the map across the boundary
runs **one-way**, reading an `Operand`; and it could not tell RV32I's
`ImmTarget` from a real µtemp, which is the same open gap as `Uop` having no
`imm`.

Agreed next steps: give `UopSeq` the cracker-sequence duties it still lacks
(stamp first/last, validate µtemp def-before-use), settle how a matcher binds
`FieldRef`s to bit segments, and add the remaining §6 deliverables to
`IsaBase` (ilen, trap policy); alternatively first Kathryn RAT/PRF
elaboration from a `RegFile` in `uarch`.

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
