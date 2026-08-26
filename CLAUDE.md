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
| `carolyne/isa/`               | description types + `ExecContext` + per-ISA packages   |
| `carolyne/uarch/`             | generic OoO engine, Kathryn code lives here           |
| `examples/regfile_demo.py`    | smallest end-to-end Kathryn flow (CPU-flavored)       |
| `generated/`                  | emitted Verilog (gitignored)                          |
| `tests/`                      | pytest; tests double as usage documentation           |

Rules: `isa` never imports `uarch` or `kathryn`. `uarch` may import the
description types but must never name a specific ISA. Per-ISA packages
contain description data only — no hardware code. There is no `contract`
package: the ISA↔µarch boundary is a DOCUMENT, and the one interface it needs
in code (`ExecContext`) lives in `isa/` because that is who writes bodies
against it. A `carolyne/contract/` existed on 2026-08-22 holding exactly that
one file and was folded in the same day; don't recreate it.

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
- **`AtomicOperand(role, name="", reg_file=None, intermediate=None)`**
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
  → field) and *raises* if the core does not carry it; `has_arch`/`has_imm`
  say what is on offer. Decision (2026-08-22): the second is **`has_imm`**, not
  `has_temp` — it is asked at the point where a consumer wants to know whether
  a slot carries an immediate (`decode_helper`'s `data_<n>`), and that is what
  a `TargetKind.TEMP` target means in every ISA written so far. Deliberately a
  RENAME OF THE PROPERTY ONLY: the field stays `intermediate`, the type
  `Intermediate`, the selector `TargetKind.TEMP`, because the µtemp concept is
  what x86 cracking runs on (AGU→addr→LOAD→ADD→STORE) and retiring it would
  retire that. COST, and it comes due at x86 bring-up: a real µtemp answers
  `has_imm` true while carrying no immediate at all, so a consumer that must
  tell the two apart cannot use this predicate — it is the `Uop.imm` gap
  wearing the name of one of its two meanings. Decision: it carries **no `width`, `is_arch`,
  `is_intermediate`** (ambiguous with two candidates — only the selection
  answers them) and **no `is_const`/`is_decoded`** (facts about the *index*,
  which the core has not got). It owns `OperandRole`
  (`SRC`/`DEST`/`DEST_W_REQ`) and `TargetKind` (`ARCH`/`TEMP`), so the import
  runs `operand` → `atomic_operand` one-way. Decision (2026-08-19): a **`name`**
  joined, optional and defaulting to `""`, validated as a Python identifier —
  it is the STEM of every hardware field a consumer builds for that slot
  (`valid_<name>`, `pr_idx_<name>`, `data_<name>`, `wb_required_<name>`), so a
  core with no name simply cannot be turned into hardware and the block that
  needs one says so (`rsv.station_cores`). Optional, not required: 58
  construction sites exist and a core is a legal description object without a
  name; `IsaBase` enforces uniqueness across the ISA for the ones that have
  one. Decision (2026-08-19): **`DEST_W_REQ`** is the third role — a
  destination whose write is REQUIRED before the instruction retires, which a
  reservation station tracks with a `wb_required_` bit where a plain `DEST`
  carries only its index. Two roles are now destinations, so `SRC_ROLES` /
  `DEST_ROLES` live beside the enum and every consumer tests MEMBERSHIP rather
  than `role is DEST` (`Uop`'s position check, `IsaBase`'s per-unit queries);
  `role.is_src`/`role.is_dest` are properties on the enum itself so the group
  test has one home. `is_write_required` on the core is what tells the two
  dest roles apart. `OperandRole` **is** an enum where `Op`
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

- **No `Op` type.** One existed until 2026-08-23 — a frozen `name` and
  nothing else, value-equal, standalone so several units could list it — and
  was removed: **the µop template IS the kind**, and `Uop` now carries the
  name. Two reasons, one from each plane. From the HARDWARE side: no record
  ever carried an op index. The kind field every record has is `uop_idx`
  (`ceil_log2(len(isa.uops))`), so `ExecContext.op_is()` had nothing to compare
  against and the generator would have had to build a uop→op decoder to
  implement it. From the DESCRIPTION side: an `Op` said only what a `Uop.name`
  says, so the vocabulary was written down twice and `IsaBase` had to
  cross-check the halves. COST, and it is real: an operation encoded twice is
  now two templates, so RV32I's ALU lists 21 (`ADD` *and* `ADDI`, `SLL` *and*
  `SLLI`) where it declared 12 ops, and a stage body guards on both — which
  `AluUnit`'s `out((UOP_ADD, UOP_ADDI), a + b)` does with one OR-ed guard per
  result. Bought with it: `uop_is` is a compare against the field the record
  already has. Don't restore `Op` from git.
- **`ExecUnitBase(name, uops, src_operands=(), dest_operands=(), needs=())`** —
  one execution-unit class; `uops` is a TUPLE of the `Uop` templates it runs,
  matched by IDENTITY (non-`Uop` members raise, never promoted from strings).
  A tuple, not a frozenset, because a `Uop` reaches a `RegFile`, which holds a
  dict, so it is unhashable — the same bargain `IsaBase` already makes for
  cores, operands and reg files. Listed once by instance and named apart:
  `unit.uop("ADD")` is the one sanctioned text→template door, for
  encoding-table rows, and it hands back the INSTANCE, which is what identity
  membership needs. Decision (2026-08-19): the unit DECLARES its
  operand slots — its PORT SHAPE, what a read/write port is sized from — where
  `src_/dest_atomic_operands_for(unit)` used to DERIVE them by walking the
  mops. Deriving made a unit's shape depend on which mops happened to exist;
  declaring makes it a statement, and `IsaBase._reject_uncovered_operands` then
  holds every µop to it: a µop may not fill a slot its unit has not got, and
  EVERY unit listing the µop must cover it, since routing is the elaborator's
  choice. Covering is by IDENTITY, the discipline the layer already runs on —
  LIMIT, and it will matter for x86: a µtemp core built per crack cannot be
  declared in advance, so µtemp slots will need a name-and-shape rule when
  cracking lands. Decision: `stages()` is the pipeline the unit IS — one
  callable per stage, defaulting to a single `build_exec` — and `build_exec`
  raises `NotImplementedError`, so a unit with no semantics is still a legal
  description object and only a generator building a real function unit demands
  one (the bargain `AtomicOperand` makes with its name). `needs` names the
  facilities a stage body wants beyond its operands (`"mem"`, `"redirect"`,
  `"trap"`) as REQUESTS, so a generator builds the right context or refuses
  early. `ExecUnit` is an alias of the base, the name a unit with no semantics
  is built under.
- **No catalog ships in code.** The §1.2 op/unit table is spec text; every
  ISA/machine declares its own `Uop`s and `ExecUnit`s (see the header block
  of `tests/test_uop.py`). Reason: importable `ALU`/`ADD` constants would
  make the natives privileged over a µop a custom FU declares — the exact
  distinction this layer refuses to make — and nothing consumes such a list
  yet. `STANDARD_UNITS`/`STANDARD_OPS` existed briefly on 2026-08-14 and
  were deleted; don't restore them from git.
- **`Uop(name, uop_idx, srcs, dests)`** — one µop
  template, and since 2026-08-23 the KIND itself: `name` is what this operation
  IS (`"ADD"`, `"ADDI"`), required, non-empty, held unique across the ISA by
  `IsaBase`. Decision (2026-08-24, later the same day as `uop_idx`): the
  template carries **NO MATCHER** — `matcher_field`/`matcher_value` lived on
  `Uop` and were DELETED, because the encoding side (`Mop` + `UopSeq`) already
  has sufficient data to pick an instruction and a template is the OPERATION,
  never its encoding. RV32I's forty funct rules moved from `riscv/uop.py` onto
  their `UopSeq`s in `riscv/mop.py`, where they sit beside the opcode they
  refine. COST, accepted: templates that differed only by matcher are now
  value-equal but for name and id (ecall/ebreak), and a decoder's guard is
  built from the mop + uop_seq pair alone (`_collect_matchers`).
  Decision (2026-08-24): **`uop_idx` is DECLARED on the template**,
  required, second positional — the id the hardware plane speaks (every
  record's `uop_idx` field), no longer read off the template's position in
  `isa.uops`. The field is AUTHORITATIVE: tuple order is declaration order and
  nothing more, so reordering `UOPS` can never silently renumber the emitted
  hardware — the stability that position-derivation could not give. `IsaBase`
  holds the declared set **unique and dense 0..N-1** (a duplicate would make
  two templates one kind; a gap would waste an encoding of a field sized
  `ceil_log2(N)`, which is how `uop_idx_width` stays len-based). Required at
  construction, not optional-with-container-demand — chosen knowingly against
  the `AtomicOperand.name` bargain, so even a throwaway fragment picks a
  number (`Uop("AGU", 0)`); the template itself validates only its own value
  (int, ≥ 0, no bool), since one template cannot see the set. Rejected:
  "field must equal tuple position" — that writes the vocabulary down twice
  and cross-checks the halves, the exact pattern the `Op` removal retired.
  `riscv/uop.py` numbers its forty 0..39 in `UOPS` order.
  Decision: the template names **only itself**, no unit — which FU executes a
  kind is a machine configuration question answered by the unit set
  (`ExecUnit.uops` read the other way round), and a µop two units both list is
  a routing choice, not an error. Cost of dropping `unit`: a bogus µop survives
  construction — it is `IsaBase` that refuses it. Templates match by IDENTITY
  everywhere (a re-spelt `Uop("ADD")` is a DIFFERENT µop), which is why a
  package shares template constants the way it shares operand ones. Operand counts are capped at the record shape
  (≤3 src, ≤2 dest, §2). `imm` is `int`
  (cracker-baked constant, x86 push→ESP−4) or `FieldRef` (extracted field).
  No first/last bound on the type — that comes from position in the cracker
  sequence (later); mem/br sub-fields deferred until FU semantics land. An
  instruction family sharing one shape is a factory function in the per-ISA
  package, not a multi-op field (a multi-op `ops` field was tried and reverted: the
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
  RV32I is in); a value alone is not. Called by `UopSeq` and `Mop` — the
  encoding side's holders; `Uop` called it too until its matcher went
  (2026-08-24).
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
- **`IsaBase(name, pc_width, pc_align, ilen_bytes, reg_files, atomic_operands,
  operands, exec_units, uops, mops)`** (`isa.py`) — the
  whole ISA, the object a generator is handed. There is no `ops` vocabulary:
  the µops ARE it (2026-08-23). Decision: `uops` and
  `reg_files` are **declared, not derived** from the mops — deriving would
  make a typo self-consistent. It cross-checks at construction: every µop and
  every reg file a mop's µops use must be declared, and every declared µop
  must be executable by ≥1 unit; the reverse (a unit listing unused ops, a
  declared-but-unused reg file) is allowed, so unit definitions can be shared
  and a class can be declared before a crack touches it. Reg files match by
  **identity** — one PRF per instance, and `RegFile` holds a dict so it is
  unhashable anyway. Names unique per vocabulary — µops joined the NAME-keyed
  half when they took their names, so a duplicated template reads as
  "duplicate uops name 'ADD'". Since 2026-08-24 it also holds the declared
  `uop_idx` set to **unique and dense 0..N-1** (see the `Uop` entry) —
  checked AFTER `_reject_undeclared`, so an incomplete declaration reads as
  the missing µop, not as its absent number. Also since 2026-08-24: the USED
  destination operands are held to **one per architectural class**
  (`_reject_shared_dest_classes`) — rename books a class's physical file
  through the slot's own port, so a second dest on one class would book it
  twice in a lane; checked HERE, ISA-wide, so dispatch carries no guard of
  its own. Lookups: `uop(name)`,
  `unit(name)`, `reg_file(name)`, `units_for(uop)` (the kind→FU map read out),
  `used_reg_files()`, `used_uops()`, `used_operands()`,
  `used_atomic_operands()`. Decision (2026-08-19): **`src_atomic_operands_for(unit)`
  / `dest_atomic_operands_for(unit)`** read `units_for()` the long way round —
  unit → the µops some mop cracks to → their slots → the cores —
  because the elaborator building ONE FU has to size that unit's operand ports
  and the container could only answer the question the other way. Two public
  halves over one private `_atomic_operands_for(unit, roles)`, because src
  cores size READ ports and dest cores size WRITE ports; the halves are
  disjoint by construction, since role lives in the core and `Uop` cross-checks
  it against slot position. It walks what the MOPS reach, not the declared
  `uops`; everything matches by identity, so a unit lists the very template
  instances the mops name. An undeclared unit is not rejected
  (neither is `units_for`'s µop) but a non-`ExecUnit` is, pointing at
  `self.unit(name)`. Core NAMES are also held unique here — unnamed ones
  skipped — since a name becomes a field name downstream. Decision (2026-08-15): `atomic_operands`,
  `operands` and `uops` are declared on the same terms — the ISA writes its
  whole vocabulary down and the container checks the chain **one link at a
  time**: a mop's µops must be declared, their operands must be declared, and
  those operands' cores must be declared, so a rule nobody wrote down cannot
  reach elaboration by riding inside a mop. All three match by **identity**
  like reg files (they are unhashable anyway — an `Operand` reaches a
  `RegFile`, which holds a dict — and identity is the discipline the layer
  already runs on: a package shares operand constants so every template naming
  rs1 names ONE object). Duplicates are rejected by instance, since none of the
  three has a name to key on; value-equal twins are fine (`AOPR_SRC_1/2` are
  two slots that agree). Cost: an ISA whose operands cannot be shared
  constants must still list them — x86 µtemp operands are built per crack and
  never shared, so mini-x86 will declare a long `operands` tuple, likely
  assembled by its crackers. Limit: the reg-file check still walks what
  operands *select*, not what their cores *offer*. Named *Base* because a
  per-ISA package
  may subclass it for fields this container doesn't model — subclasses must
  stay `frozen=True` and stay **data**: overriding `op()`/`units_for()`/
  `__post_init__` would put ISA-specific behavior on the elaborator's path.
  Decision (2026-08-16): three **addressing scalars** joined the vocabularies —
  `pc_width`, `pc_align` (bytes), `ilen_bytes` — one subject, "where does an
  instruction sit and how long is it", and the container had none of it. The PC
  is not a register class (§4.3) but its WIDTH is still an ISA fact: fetch, the
  redirect path, the branch-target adder and the ROB's pc cannot be sized
  without it, and the contract doc has the same gap (§4.3 claims the ISA
  influences the PC "only via `br` and `ilen`"). `ilen_bytes` is §6 deliverable
  three finally getting a home — `riscv/field_match.py` held `ILEN_BYTES` with a
  comment saying so. Declared, not derived: pc_width from the integer class
  would make the container name a specific reg file, the one thing it must not
  do (a *package* may still write `PC_WIDTH = X_LEN` — that's the ISA quoting
  its own spec). Required, no defaults — a default 32 is a silent wrong answer
  for a 64-bit ISA. **Three plain fields, not an `InstrAddr` type**: the
  container states them itself and the cross-checks ride in the `__post_init__`
  that already runs; a type earns its place the day `ilen_bytes` grows §1.3's
  variable-length function form, which needs validation of its own. Checks:
  `pc_align` a power of two (alignment is a mask), `ilen_bytes` a multiple of it
  (aligned steps from an aligned start stay aligned), `pc_width` wide enough to
  address past one aligned unit. `pc_align_bits` is **derived** (the always-zero
  low bits a stored PC can drop), the same store-the-count/derive-the-log2
  bargain `RegFile.amount`→`index_width` makes. NOT here: the reset vector —
  where a core starts fetching is machine configuration, not an ISA fact.
  Trap policy joins when that type exists.

**`carolyne/isa/riscv/`** is the first per-ISA package, deliberately a
TEMPLATE skeleton: `reg.py` (`x_file()` → x0..x31, x0 via `const_regs`;
**PC is deliberately not a register class** — it is front-end/ROB state, not
something the engine renames through a PRF port, so a 1-entry `pc` file was
drafted and deleted), `exec_unit.py` (`exec_units()` + `AluUnit`, the units the
machine provides and what the ALU computes), `field_match.py` (32-bit field positions, the addressing group
`PC_WIDTH = X_LEN` / `PC_ALIGN = 4` / `ILEN_BYTES = 4` that `Rv32i` names as its
three scalar defaults,
and `FORMATS` = the six base formats R/I/S/B/U/J as `union`s of those fields,
each tiling the word exactly once — declared but not yet consumed, since a
`Mop` has no format slot), `uop.py` (`UOP_*` + `UOPS`, plus the `LOADS` /
`STORES` / `BRANCHES` groups the units build from — it is the whole operation
vocabulary since `op.py` went on 2026-08-23), `mop.py` (`MOP_*` +
`MOP_TABLE` → 11 opcode-group `Mop`s, exhaustive over `UOPS`), `rv32i.py`
(`Rv32i`, an `IsaBase` **subclass** — exec_unit.py also holds the ALU's
semantics, `AluUnit`, see the `ExecContext` entry below — supplying every vocabulary as a field
default — `Rv32i()` is the whole description, and `Rv32i(name=...)` varies one
part without a builder signature for the rest; it stays DATA, no method
override, so every inherited cross-check still runs. An `rv32i()` factory stood
there until 2026-08-15; don't restore it). The table is grouped by OPCODE, not by
format: the two are different partitions — I-type spans LOAD, OP-IMM, JALR and
SYSTEM — so a format-grouped table would need one `Mop` matching four opcode
values, which one matcher cannot say. `MOP_TABLE` is a module constant rather
than a builder function, on the same frozen-data / shared-instance terms as
the operand constants below. It builds and passes every container cross-check.
The operand rules (`OPR_RD/OPR_RS1/OPR_RS2`, and the six `OPR_IMM_*`) are
**module constants**, so the register class they target is one too:
`reg.RegFile` — a shared instance built by `x_file()`, which `Rv32i` also
declares. `IsaBase` matches reg files by identity, and sharing constants
makes those the same object by construction. Accepted cost: two `Rv32i()`
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
should not); and a matcher **discriminates but does
not extract** — nothing says where each segment of a scrambled immediate lands
in the assembled value, so a decoder can now pick the instruction and still not
build its immediate. Three former gaps are closed and *used*: the instruction's
own PC — which no operand can name, since PC is not a reg file — is read off
the µop record as `ExecContext.pc()` (2026-08-22; `AluUnit`'s AUIPC uses it,
the jumps' link value will), `FUNCT3_7 = FUNCT3
| FUNCT7` spans both fields, and **every matcher in the package now states its
value** — `FM.val(...)` beside the field, opcode values on the eleven `Mop`
groups and funct values on the `UopSeq`s (since 2026-08-24 — templates carry
no matcher; LUI/AUIPC/JAL's seqs name no field: their opcode alone identifies
them, and that is the Mop's rule). So
add-vs-sub and ecall-vs-ebreak are genuinely distinguishable, and
`check_matcher_pair` catches a mis-sized value at import.

One gap was closed by enumerating instead of extending the record: memory
width/sign and branch condition are **distinct µops** (`LB/LH/LW/LBU/LHU`,
`SB/SH/SW`, `BEQ/BNE/BLT/BGE/BLTU/BGEU`, tuples `LOADS`/`STORES`/`BRANCHES`),
and `AUIPC` is its own µop rather than an `ADD` missing its PC source. Generic
`LOAD`/`STORE`/`BR_COND` kinds would have needed record sub-fields that only
those kinds read — a second way of saying what `kind` already says. Cost: 40
templates and more cases per FU; benefit: the §2 record stays as written and
the decoder never fills a field it doesn't understand.

A first `Layout`/`Mop` pair (encoding metadata + macro-op variants binding an
encoding to a µop sequence) was written and then removed as sloppy, and the
current `mop.py` is the from-scratch redesign — the encoding side of the
contract (§1.3) is still open; don't restore the old one from git.

A `PhyOperand` (the post-rename record slot: role, slot, class, physical index
width, const-bypass value) was built on 2026-08-15 and
removed the same day — a record type waits for the elaborator that consumes
it. Don't restore it from git. What it surfaced is worth
keeping: a physical index is a run-time value, so the map across the boundary
runs **one-way**, reading an `Operand`; and it could not tell RV32I's
`ImmTarget` from a real µtemp, which is the same open gap as `Uop` having no
`imm`.

**`carolyne/isa/exec_context.py`** — **`ExecContext`** (2026-08-22): the
interface a unit's stage body (`build_exec`, each entry of `stages()`) is
written against, FU-plan step 2. Decision: it lives in **`isa/`**, not a
`contract` package of its own — the ISA layer is who WRITES bodies against it,
`uarch` only implements it, so declaring it here keeps the dependency arrow the
layout already has (uarch reads the description, never the reverse) rather than
adding a third package that one file would live in alone. It is the layer's one
asymmetry — every other module here is frozen DATA and this is an interface —
but it is still elaboration-plane by §2's test: it holds no runtime value, only
the rules for reaching one. Exported from `carolyne.isa` beside the description
types. Decision: a `runtime_checkable` **`Protocol`**, not an ABC — conformance
is structural, so neither a per-ISA package nor a test double imports anything
to comply, and the module itself imports nothing AT ALL (the type hints are
`Any`; the values are opaque on purpose), so it adds no edge inside `isa`
either and a plain same-package import needs no `TYPE_CHECKING` guard. The surface is
`src`/`write`/`keep`/`kept` plus the flow three
`when`/`until`/`while_` (zif/scwait/cwhile), and TWO additions: **`uop_is(uop)`**
(named `op_is` until 2026-08-23), because one
unit serves every kind it declares so a body must branch on the record's kind —
and the kind the record HAS is `uop_idx`, so the key is the description's own
template constant and the compare is against the field that exists — and
**`pc()`**, because the record carries the µop's own PC (the RSV entry already
stores it) and that is the one PC-relative input no operand can name. `pc()`
is what closes the auipc/link-value gap in the contract direction.
Decision (2026-08-22): **no `imm()`**. One was drafted and cut the same day —
an immediate operand FILLS A SOURCE SLOT (`ImmTarget`; `OPR_IMM_*` select
`AOPR_SRC_2`/`_3`), so `ctx.src("src_2")` already reaches it and a second
accessor would be a second way to read one value, backed by nothing while
`Uop` has no `imm` field. The interface FOLLOWS that question rather than
leading it: the day contract §2's own immediate field lands, the accessor
arrives with it and the `OPR_IMM_*` operands leave `srcs` together. Meanwhile
a body reads its immediate by slot name, which is what RV32I's LUI
(`out(MOV_IMM, b)`) and every I-type shape already do. Three
ground rules, stated in the module header because every body leans on them:
values are OPAQUE (Python operators only — ints under a fake, Kathryn signals
under the real one, and one body must mean the same thing both ways, so sign
handling is structural: flip-the-sign-bit compares, XOR-subtract sign-fill);
a WRITE TRUNCATES to the destination's width (what a write port does — `a - b`
wraps identically in both worlds); and the BODY ALWAYS EXECUTES (`when`
guards the effects, never the Python code, so a body may not branch in Python
on a runtime value — elaboration runs every block whatever the values).
**`AluUnit`** (`riscv/exec_unit.py`) is RV32I's first semantics, an
`ExecUnitBase` subclass. Decision (2026-08-22): it and `exec_units()` live in
their own module, the `riscv/` half of the `isa/exec_unit.py` pairing every
other file in this package already has (`operand`, `reg`, `mop`, `uop`,
`field_match`). They move TOGETHER, which is what makes the split legal: the
factory needs the class and the class needs the vocabulary, so moving the class
alone would have the vocabulary file import the new module while the new module
imports it back — a cycle. Moving both leaves the dependency one-way; since
2026-08-23 the vocabulary it reads is `uop.py` itself, so a unit is declared
from the very templates the mops name. µops are referenced `U.UOP_ADD` through `from . import uop as U`.
All twenty-one templates write ONE destination through a local
`out(uops, value)` helper that takes ONE template or a GROUP of them — the
register form and its immediate form compute the same thing off src_2, so they
share one OR-ed guard — and the body is a list of guarded results whose guards
are mutually exclusive by construction. Which is why it states NO priority: the
"equal priority is not statement order" trap needs two drivers that can be live
at once, and `uop_is` guarantees they cannot. `ctx.src("src_1")`
is safe for the same reason the port shape is declared: `_reject_uncovered_operands`
has already held every ALU µop to the two slots the unit declares, so a name the
body reads is a name the record has. MOV_IMM passes src_2 through (the assembled
U-imm rides there, UOP_LUI), AUIPC is `ctx.pc() + b`. LIMIT: sign-fill written
structurally (`msk = (a & sign) >> sh; ((a >> sh) ^ msk) - msk`) costs a SECOND
barrel shifter where a hand-written SRA muxes the fill bit into one — the price
of a body that means the same thing on ints and on signals, and revisable if the
FPGA numbers say so. mem/control now declare
`needs=("mem",)`/`needs=("redirect",)` — requests recorded ahead of the step-5
facility contracts; system stays plain until trap policy exists. Checked against
Kathryn's DSL: `- ^ & | << >> <` all exist on a signal and take an int operand,
and `__lt__` maps to `LogicOp::RelationLe`, which emits `<` — "Le" is *less*,
"Leq" is less-or-equal, so SLT/SLTU are not silently off by the equal case. The FAKE
context lives in `tests/test_alu_semantics.py`, deliberately unshipped: a test
double is usage documentation, and the test file demonstrates all three ground
rules (a `when(False)` block still runs, an unfilled slot reads like an idle
wire, truncation makes wraparound come out right) with zero Kathryn — the
cheapest possible test of an ISA's arithmetic.

**`carolyne/uarch/o3/config.py`** — `CPUO3_Config` is the ISA plus the numbers
the ISA does not decide, and it never copies a fact out of the description (no
`pc_width` field of its own) — it DERIVES, so a block reads one object and
never has to know which half a number came from. Decision (2026-08-19):
**`commit_lanes`** joined `fe_lanes` as the machine's second WIDTH — the most
instructions that may retire in a cycle, against the most µops that may arrive.
Both are CEILINGS the hardware is sized to, not counts of what moves: commit
retires whatever is ready up to that many. Separate knobs,
because a core may retire narrower than it fetches and neither is derivable
from the other; this is the field `reg_arch_mng`'s header was waiting for when
it said "port counts are parameters… when the config grows those fields they
replace these arguments", so its `commit_port` argument can now come from here.
REQUIRED, no default, on the same terms as every other knob — a default is a
number nobody chose — which is why every construction site names it. Checked
against the ROB (`commit_lanes <= rob_depth`): a cycle cannot retire more
instructions than the buffer can hold.

Decision (2026-08-22): **`RsvSpec` states what KIND of station it is** —
`rsv_type`, one of `RsvType.RSV_EXEC` / `RSV_BRANCH` / `RSV_LD_ST` — and the
kind is what decides the extra fields its entries carry: an exec station its
`pc` (auipc reads it), a branch station `pc` and `npc` (it has to compare
against the next one), a load/store station NEITHER, since an address is a
value it computes rather than one it is handed. Declared, not derived from the
units: two machines may split one unit set differently, and a station feeding
alu AND control still has to say which shape its entries have — which is
exactly the case RV32I's tests hit, where one station feeds every unit.
REQUIRED, no default, on the `commit_lanes` terms — even though defaulting to
`RSV_EXEC` would have been behavior-preserving (its field set is exactly the
`pc` the base used to carry unconditionally), which is what makes it a real
choice rather than a free one; every construction site names it.
`rsv_type_fields(rsv_type, pc_width)` is where the pairs are SIZED, because a
`RsvSpec` is built standalone and never sees a config — the same reason the
config derives rather than copies. The NAMES live in `_RSV_TYPE_FIELD_NAMES`
separately, since a spec must check its own extras against them without a
pc_width to hand; every kind's fields are PC-shaped today, which is what lets
one width size them all. **`extra_fields`** is the machine's own `(name,
width)` list on top, validated as pairs (identifier, width ≥ 1, unique, not
shadowing the kind's) — the record-wide collision check belongs to
`rsv_entry_shape`, which is the only place operand field names are known.

**`carolyne/uarch/o3/rsv_helper.py`** — `build_rsv_table(config, rsv_spec, name="")`
builds ONE reservation station's entry table (2026-08-19). `RsvEntryBase`
states the shape every station has (`valid`, `is_spec`, `spec_tag`, `uop_idx`,
`rob_des_idx`) — `rob_des_idx` names the ROB entry the µop belongs to,
`ceil_log2(rob_depth)` wide, and is what a writeback reports against and what
commit retires; `RsvO3Entry` adds the age track and `RsvIOREntry` adds nothing, since
position in an in-order station IS the order. The builder adds the part that
varies with the ISA: one field group per `AtomicOperand` the station's units
read or write, named after the core —

| core                    | fields                                  |
| ----------------------- | --------------------------------------- |
| src on a register class | `valid_<n>`, `pr_idx_<n>`, `data_<n>`   |
| src on a µtemp only     | `data_<n>` only                         |
| `DEST`                  | `pr_idx_<n>`                            |
| `DEST_W_REQ`            | `wb_required_<n>`, `pr_idx_<n>`         |

A µtemp source gets data ALONE because there is no PRF entry to wake on — the
value rides with the µop (RV32I's immediates are exactly this, via
`ImmTarget`). A core offering BOTH targets is sized off the arch one: `pr_idx`
from `config.phy_idx_width(reg_file)`, `data` from the class width. A µtemp
DESTINATION *raises* — the config sizes a physical file per register CLASS, so
there is no index width for one, and x86's AGU will surface that gap the day it
lands. Decision (2026-08-22): the **PC is not in the base**. Which stations carry one
is a question of what KIND of station it is, so `pc`/`npc` arrive as ADDED
fields from `rsv_spec.entry_fields(config.pc_width)` — see `RsvType` below —
and a load/store station carries neither. They are added LAST, after the
operand groups, so a name colliding with anything already in the record is
caught here; the spec can only check its extras against its own kind's, never
against an operand's. Decision: the signature takes the **config**, not just
the `RsvSpec` — `spec_tag`, `pc` and `uop_idx` cannot be sized from a spec that
holds only size + units. `uop_idx` is `CPUO3_Config.uop_idx_width` =
`ceil_log2(len(isa.uops))` — it names WHICH µop of the ISA's vocabulary the
entry holds, so one index means the same µop anywhere in the core. It is NOT
the ROB index (that counts in-flight instructions and is narrower: 6 bits vs 5
for RV32I on a 32-deep ROB). `track` is `ceil_log2(size)`, so an out-of-order
station with one entry raises rather than asking Kathryn for a 0-bit field.
The table is `reset(valid=0)`: a station powers up empty. `station_cores`
gathers srcs then dests across every unit of the station, deduped by identity,
and refuses an unnamed core or a name collision.

**`carolyne/uarch/o3/rsv.py`** — **`RsvBase`** (2026-08-19), the station itself:
the `table` of waiting entries, the `exec_src` row the FU reads, and the events
that move them, modelled on the C++ engine's `rsv.h`. `build_issue` is left
abstract (`NotImplementedError`) — which ready entry goes next is the station's
policy, age order out of order vs the head in order — so a subclass says it and
everything else is shared. `slot_ready(row)` ANDs `valid` with `valid_<n>` over
the ARCH sources only, since a µtemp/immediate has no physical register to wait
for; `wake_operands` is that subset, computed once at declaration. `on_bypass`
takes `RsvBypass(reg_file, valid, pr_idx, data)` records and only wakes sources
naming the SAME class — two PRFs number their entries independently, so a bare
index would cross-wake. `on_suc_pred` masks the resolved tag out
(`spec_tag &= ~suc_tag`, `is_spec = spec_tag != 0`) rather than comparing
equal, because an entry may sit under several open speculations — the same
idiom `Rt`/`Mpft` already use. Decision: **no new priority rungs**. The C++
ladder (mispredict > writeEntry > the rest) maps exactly onto the engine-wide
one: a dispatched entry is written at `PRI_RENAME`, since dispatch and rename
are one instant, and a squash is `PRI_MIS_PRED`. Issue, bypass and a resolved
prediction stay on the bottom rung. `rsv_helper` grew `rsv_entry_shape()` so
the table and the slot cannot drift, plus `build_rsv_slot()` for the one-row
`exec_src`. NOT here: the `SyncPip`, the sim probes, and the o3 sort-bit rung
of the C++ original; the age-track maintenance lands with the o3 subclass.

**`carolyne/uarch/o3/rsv_o3.py` / `rsv_ior.py`** — the two issue policies
(2026-08-19), from the C++ `orsv.h` / `irsv.h`.

**MANY WRITERS, ONE ISSUE** is the shape of both. There is one write port per
`fe_lanes`, since every front-end lane may dispatch in the same cycle and any
of them may be aimed at this station; issue stays single, one entry per cycle
to one unit. A lane says who it is for: the bus carries `rsv_id` and
`lane_targets_me()` is the check — the station answers it on the way in and
stores nothing, so no entry has an `rsv_id` field. `free_slots()` hands each
port a DIFFERENT entry, which is what lets two lanes land in one cycle.

**`RsvO3`** issues the OLDEST ready entry. Decision, and the deliberate
departure from the original: age is the STATION's own business — it keeps a
`track_ptr` counter and stamps every entry dispatched in ONE CYCLE with the
same value, where the C++ read the register file's RRF cycle
(`regArch.rrf.nextRrfCycle`). The track counts dispatch cycles, so lanes of one
cycle are equally old and the fold breaks the tie structurally; nothing outside
has to publish a cycle id. `is_lower_track` is the epoch bit for the counter's
wrap: set means "a wrap behind", so it is older; within one epoch the smaller
stamp is older. On the wrap every entry already in the table is stamped older
(`roll_track_epoch`) at **`PRI_TRACK_ROLL`**, a new bottom rung that must LOSE
to the dispatch write at `PRI_RENAME` — entries arriving that cycle belong to
the new epoch. That is what the C++ `RSV_SORTBIT_RST_PRED_PRIORITY` was for,
and the emitted Verilog shows the roll emitted before the write. LIMIT, and it
is a real one: an entry waiting through more than one wrap compares as merely
old rather than oldest. That costs order, never correctness — what issues is
always ready, so the age track is a heuristic and this is the price of not
reading the RRF.

`free_slots(dispatch)` gives each port its own entry, and it takes the DISPATCH
BUS to do it: a port IS a lane, fixed to it, and a lane may be carrying a µop
for another station this cycle, so what an earlier port actually takes here is
only knowable from the lanes. Each port runs its own Karray **reduce** over the
table: what is INJECTED at the leaves is `~valid & not claimed by an earlier
lane`, and what comes back is the INDEX of a row where that holds — the free
bit reduced with its index, log2(size) deep. Port k's leaves drop a row only
when an earlier lane both landed here and landed on it
(`accepted_p & (idx_p == row)`); a lane bound elsewhere excludes nothing.
Decision: the fold carries its answer in the **`track` slot**, because an
extra that REPLACES a field is the only kind a caller can read back — an
appended one has no position in the record, so `read_field_hcps` cannot map it
out — and `track` is exactly index-wide by construction. `valid` carries
"something free under me" up the same tree. A first version captured the root
node in a Python dict and returned that; a second ranked the free rows by
prefix count (`sum_cnt(is_free[:i]) == k`), which could not say "unless that
lane went to another station" at all. The fold muxes the whole record on the
way, since Kathryn carries every field through a reduce, but both replaced
slots are expressions and nothing reads the rest — the emitted Verilog keeps
ZERO mux wires from the free folds, only the select logic.

The winner is chosen by a Karray **REDUCE read** (`table[select_fn]`) rather
than a hand-built fold: a reduce carries the WHOLE record at every level, so
one fold builds the comparison tree once and drops the winning row on
`issue_row` — the wire slot the issue block reads, the C++'s `WireSlot iw`.
`entry_ready` and the one-hot ride up as extras, so a node compares subtree
answers instead of rebuilding them, and the node whose covered indices are the
whole table IS the root (a structural test, not an assumption about the order
the fold visits nodes in). Issue then runs inside `cwhile` + `zync` on the
execution unit's `PipCon`: a busy unit STALLS the station, where a plain `zif`
would have cleared the entry into a unit that never took it.

**`RsvIOR`** issues the head, through the same `cwhile`/`zync` gate. Its lanes
land in a RUN from `alloc_ptr` that COMPACTS — a port's offset is how many
earlier lanes are actually dispatching here, so a lane bound elsewhere leaves
no gap — and a lane may only land if every earlier lane bound for this station did — in order, a hole would be an entry issuing
before one dispatched ahead of it — after which the pointer moves on by
`sum_cnt(accepted)`. Decision: TWO POINTERS (`alloc_ptr`, `head_ptr`)
instead of the original's searches over the busy column — an in-order station's
occupancy is contiguous by construction, so the search is answering a question
the pointers already know. A squash always takes the YOUNGEST entries, so the
survivors stay a prefix from the head and the allocation pointer is
`head + popcount(survivors)`, computed with `sum_cnt` at `PRI_MIS_PRED`; the
head does not move. The count reads the pre-clock valid bits, so an entry
issuing in the same cycle is still counted — correct, because the head advances
by one at the same time. The row count must be a POWER OF TWO, the bargain
`Prf` already makes: both pointers step modulo the table, so at that size the
modulo is the register width and no wrap compare is built — and at least TWO,
since one entry leaves the pointers 0 bits wide (that used to surface deep in
Kathryn as "dynamic index needs >= 1 bits, got 0").

The modulo is also where the lane run can bite: a port's slot is
`alloc + count(wants[:port])` MOD size, and two WANTING ports collide exactly
when their offsets differ by a multiple of the table — which needs MORE write
ports than entries, since the largest difference is `write_ports - 1`. Decision:
refuse `write_ports > size` at construction rather than test `offset < size` per
port in hardware. The bound is `<=`, not `<`: at exactly `size` the largest
difference is `size - 1`, which cannot be a whole table. A runtime guard was
built first and removed — it cost a comparator on every port past the table to
buy a configuration (a station shallower than the front end is wide) that can
only take `size` lanes a cycle anyway, and refusing is the bargain this file
already makes twice over for the power-of-two size and the two-entry floor.
`RsvO3` needs no bound at all: port k's fold drops what earlier lanes took, so
once the rows run out the later folds find nothing free and those ports accept
nothing.

Both stations read two shared facts back off `RsvBase` rather than restating
them: `lanes_for_me(dispatch)` is the per-lane "this one is for me" bit, built
ONCE because the slot search and the write side both ask, and
`entry_squashed(row, fix_tag)` is the one definition of which entry a
mispredict kills — the base clears them with it, and `RsvIOR` counts the
survivors with its negation instead of writing the predicate a second time.
NOT shared: the free-slot fold. An in-order table is contiguous by
construction, so `RsvIOR` COMPUTES its slot from the pointer where `RsvO3`
searches for one; a reduce there would be looking for something already known.

Decision (2026-08-23): a dispatch lane is the **CORE-WIDE bus**
(`dispatch_helper`), not a row of the station's own shape —
`rsv_helper.build_rsv_dispatch()`, which built `lanes` rows of
`rsv_entry_shape` plus an added `rsv_id`, is DELETED. One bus per station only
worked while the bus was shaped per reader; now that `DispatchEntryBase` declares
the machine half, a lane holds whatever the µop turns out to be and every
station reads the same rows. And `rsv.py` needed NO CHANGE for it:
`write_entry` stays the whole-row `|= src_row` it was, because Kathryn's k2k
assign pairs fields by NAME AND WIDTH and skips the destination fields with no
match (§6) — a station takes the fields it keeps out of a wider lane, and the
rest of the bus goes nowhere. The skipped ones are exactly `track` /
`is_lower_track`, which no front end could answer and `RsvO3.write_entry`
substitutes. An adapter WAS built the same day and reverted whole: a
`disp_fields` intersection, a `lane_fields` copy beside `row_fields`, a
`SELF_WRITTEN` tuple and a `_dispatch_filled` refusal that held every entry
field to "the bus, the station, or the machine fills this". It restated in
Python what k2k already does in the arena, and it put a list of `RsvO3Entry`'s
field names on `RsvBase`. Don't restore it from git — `rsv.py` is shape-blind
on purpose.

Shared additions on `RsvBase`: `rsv_idx` + `try_write_entry(target_idx, ...)`
(the C++ `RSV_IDX` / `tryWriteEntry`, for a dispatch bus that names one
station), an abstract `free_slot()` (where a dispatch lands is policy too), and
`row_fields(src_row, **overrides)` — the spelling for "copy this row but say
something else about two of its fields". Both `write_entry` (stamping the age)
and `on_issue` (the `tryOwSpecBit` fixup, clearing a speculation that resolves
in the issue cycle) use it, because layering a second write on a whole-row copy
would put two writes at EQUAL priority and equal priority is not statement
order. `rsv_helper.rsv_field_names()` is what makes that substitution possible.

**`carolyne/uarch/o3/operand_field.py`** (2026-08-19) — the ONE place a µop
operand's hardware fields are named and sized. Both records carry a group per
operand and they differ only in WHICH kinds they keep, never in what a kind is
called or how wide it is, so the vocabulary (`VALID`, `DATA`, `PR_IDX`,
`AR_IDX`, `WB_REQUIRED`, `ACTIVE`) and the width rules live here and a caller
passes the kinds it wants: a station's source is `(VALID, PR_IDX, DATA)` — or
`(DATA,)` on a µtemp — its destination `(WB_REQUIRED, PR_IDX)` or `(PR_IDX,)`,
and the ROB's `(ACTIVE, WB_REQUIRED, PR_IDX, AR_IDX)`. Decision (2026-08-22):
**`WB_REQUIRED = "wb_required"`**, renamed from `REQUIRED = "required"` —
"required" alone never said required for WHAT, and what the bit tracks is the
WRITEBACK landing before the instruction may retire. The VALUE moved with the
constant, so the generated fields are `wb_required_<n>`: the value's only job
is to be the field-name stem, so a `WB_REQUIRED = "required"` would leave the
misleading name exactly where it costs most — in the emitted Verilog and the
waveform — and would make this the one constant here whose name and value
disagree. `wb_` is already the prefix `RobEntry.wb_fin` established for
writeback state. A width of ZERO means "nothing
to store", which is what drops `ar_idx` on a one-register class. `field_name()`
is the single spelling, and the CONSUMERS use it too — `RsvBase.slot_ready` and
`on_bypass`, `RsvO3._folded`, the ROB's reset — so a record and the logic
reading it cannot disagree about a name. `require_named` and the µtemp refusal
are here for the same reason: one message, `where` naming the caller, the way
`check_matcher_pair` does in the ISA layer.

**`carolyne/uarch/o3/rob_helper.py`** — `build_rob_table(config, name="rob")`
(2026-08-19), the reorder buffer's entry table, built the way a station's is.
`RobEntry` states the fixed half (`wb_fin`, `is_branch`, `is_store`, `pc`, the
PC sized from `config.pc_width`); the builder adds one field group per
DESTINATION atomic operand:

| field             | width                            | what it is                 |
| ----------------- | -------------------------------- | -------------------------- |
| `active_<n>`      | 1                                | this instruction writes it |
| `wb_required_<n>` | 1                                | the writeback must land first (DEST_W_REQ cores only, 2026-08-26) |
| `pr_idx_<n>`      | `config.phy_idx_width(reg_file)` | rename's physical register |
| `ar_idx_<n>`      | `reg_file.index_width`           | the architectural register |

Only DESTINATIONS: sources are a station's business, and what RETIRES is a
write. The set is core-wide (`isa.used_atomic_operands()` filtered to dests),
not per unit, since anything that retires passes through this one table — the
opposite end of the same question `src_/dest_atomic_operands_for(unit)` answers
for one FU. TWO index widths, from different places: `pr_idx` from the machine's
physical file, `ar_idx` from the ISA's class, and commit is exactly the hop from
one to the other. A one-register class (x86 FLAGS) gets NO `ar_idx` — its
`index_width` is 0, there is nothing to choose, and a 0-bit field is not a legal
width. A µtemp destination RAISES: it dies at the instruction boundary, so it
has no architectural register to retire into. The table is
`reset(wb_fin=0, active_<n>=0)`, so nothing powers up claiming a register.

**`carolyne/uarch/o3/rob.py`** — **`Rob`** (2026-08-19), the reorder buffer and
the commit stage that drains it, from the C++ `rob.h` / `rob.cpp`.

**TWO POINTERS AND A COUNT.** `alloc_ptr`, `com_ptr` and `used_entry_cnt`
(named `in_flight` until 2026-08-26 — a metaphor where the file's other
counts say what they count; `lane_in_flight` became `lane_used` with it). The count
is what tells a FULL buffer from an empty one, which two pointers of the same
width cannot, and it takes ONE clocked write from `on_update_meta` — the Prf
bargain, so allocating and retiring in the same cycle cannot lose each other.
The depth must be a power of two and at least 2, the same refusals `RsvIOR`
makes. Decision: the ROB keeps its OWN index space, where the C++ indexes by
the RRF pointer — this engine renames each register class into its own physical
file, so there is no single rename pointer to borrow.

**A DISPATCH GROUP LANDS WHOLE OR NOT AT ALL.** `free_slots` asks once whether
the cycle's whole bundle fits (`wanted <= depth - used_entry_cnt`) and every lane
reads that one answer, so a partial dispatch — which would leave the rest of
the group to be re-formed behind it — cannot happen, and no hole-blocking chain
is needed the way `RsvIOR` needs one. It also makes `fe_lanes > rob_depth` a
refusal at construction: a bundle that cannot fit an EMPTY buffer could never
dispatch. The compare is written `wanted <= depth - used_entry_cnt` rather than
`used_entry_cnt + wanted <= depth` so both sides stay inside the count's width.

**COMMIT IN GROUPS, UP TO AND INCLUDING A BARRIER.** Lane k retires only if
every earlier lane retires AND no earlier lane is a branch or a store, so a
barrier is always the LAST of its group and at most one retires per cycle —
which is what lets the store buffer pop once and the predictor update once. It
is the C++ `com2Cond = wbFin & ~com1(isBranch) & ~com1(storeBit)` written for
any number of lanes, as a running AND down the group.

**COMMIT DRIVES `RegArchMng` DIRECTLY** — it is the commit stage `reg_arch_mng`'s
header says will "reach `mng.rt(rf)` and `mng.prf(rf)` and drive them itself" —
under TWO conditions, not one. **ACTIVE** alone frees the physical register:
rename allocated it, so commit returns it whether or not anything was written
into it. **ACTIVE and REQUIRED together** are what make the write
architectural: only then does the value move PRF→ARF and the rename table stop
pointing at the physical register. Freeing on the narrower condition would leak
a register every time a claimed write was not required. `Prf.on_commit(port, valid)`
is called ONCE per lane per class, since the port is a wire and a second drive
would be a second answer. The ROB refuses a `RegArchMng` whose commit port
count does not EQUAL `commit_lanes` — a lane and a port are the same thing
counted twice, so they must agree rather than merely fit. A one-register class retires to `val(1, 0)`: it
stores no `ar_idx` because there is nothing to choose.

The commit body sits in a **`pip`** block on the stage's `PipCon`, and nothing
retires in a squashed cycle because the mispredict is bound as that arbiter's
RESET — what the C++ gets from its `PipStage`. The DRIVER binds it, not the
ROB: an arb takes one reset, and the block that created the arb is the one that
knows what else contends on it. `on_mis_pred(rob_idx)` then rolls the TAIL back to one past the
branch (the branch still retires) and recomputes the count as the run from the
head to it inclusive; the head does not move.

**`carolyne/uarch/o3/fetch_helper.py`** — `build_fetch_table(config,
name="fetch")` (2026-08-22), the fetched-instruction record, one row per
`fe_lanes`, with `fetch_entry_shape()` beside it. `FetchEntryBase` moved here out of
`fetch.py`, which now holds the Fetch MODULE only — the same table/module split
`rsv_helper`/`rsv` and `rob_helper`/`rob` already have, so a record can be
sized and probed without elaborating the stage that owns it. It is the ONE
place raw ISA bits are legal: `instr` is the encoded word memory returned, and
decode is what turns it into a `uop_idx` — nothing downstream of decode may
carry it (§2). Decision: **ONE array of `fe_lanes` rows**, where `fetch.py`
built a LIST of `fe_lanes` arrays of one row each. Statically indexed either
way, so the registers are identical; one array is what `FetchEntryBase`'s own comment
already documented (`FetchEntryBase(..., (lanes,), "fetch", ...)`) and what every
other record in the core is. Decision: both fields declared **`kaf()` with no
width**, where they were `kaf(32)` — a default that suits RV32I is a silent
wrong answer for a 64-bit ISA, so the instantiation must state them, the same
bargain `IsaBase.pc_width` makes. NOT here: a `valid` bit. A lane's occupancy
is the fetch stage's `pip` grant, and a field beside it would be a second
answer to one question — the same reason the FU plan gives for a stage's grant
BEING its valid bit.

**`carolyne/uarch/o3/dispatch_helper.py`** — `build_dispatch(config,
lanes=None, name="dispatch")` (2026-08-22), the bus from rename to the back
end, one WIRE row per `fe_lanes`, carrying a field group per atomic operand.
Core-wide (`isa.used_atomic_operands()`, srcs then dests), because a lane is
SHAPED before it is ROUTED and has to hold whatever the µop turns out to be.
Decision: which kinds a group carries is **DECLARED from the operand's role and
target**, not gathered from what the ROB and the stations want between them:

| operand              | kinds                                       |
| -------------------- | ------------------------------------------- |
| src, register class  | `valid` `data` `pr_idx` `ar_idx` `active`   |
| src, immediate only  | `valid` `data` `active`                     |
| dest, register class | `pr_idx` `ar_idx` `active` `wb_required`    |
| dest, µtemp only     | `active` `wb_required`                      |

A SOURCE never carries `wb_required` — it is a destination's promise that the
writeback lands before the instruction retires, and a source writes nothing. A
DESTINATION never carries `valid` or `data` — it waits on nothing, and at
dispatch its value does not exist yet because the FU has not run. The
index rule is `operand_field`'s, not a choice made here: `pr_idx`/`ar_idx` name
a register OF A CLASS, so an operand that only ever names a µtemp carries
neither, and a one-register class still drops `ar_idx` on the 0-width rule.
`SRC_KINDS`/`DEST_KINDS` are the two tuples and `dispatch_operand_kinds()` is
the one place the target narrows them. Decision (2026-08-23): `DispatchEntryBase`
(named `DispatchBase` until 2026-08-24 — the record-class naming every other
table already has) now DECLARES the machine half beside the operand groups — `valid`, `is_spec` +
`spec_tag`, `uop_idx`, `rob_des_idx`, `rsv_id`, `is_branch` + `is_store`,
`pc` + `npc`. It is the UNION of what the readers keep, not a copy of any one
of them, because a lane is shaped before it is routed and the same row is read
by the ROB (`is_branch`/`is_store`/`pc`), by a station (`is_spec`/`spec_tag`/
`uop_idx`/`rob_des_idx`, plus `pc`/`npc` if its KIND carries them) and by every
station at once (`rsv_id` — the field that lets each take only the lanes naming
it). `valid` IS declared here where `FetchEntryBase` refuses one: a wire bus has no
`pip` grant to read occupancy off, so the row has to say so itself. Widths come
from the config exactly as the readers' do (`sptag_len`, `uop_idx_width`,
`rob_idx_width`, `pc_width`) and `rsv_id` from `rsv_helper.rsv_id_width` —
imported rather than restated, so the width a station compares against and the
width a lane carries are one number. The stations read THIS bus as of the same
day (`rsv.py`), which is what retired `build_rsv_dispatch`. STILL not here: any
pooling against `rsv_entry_shape`/`rob_entry_shape`. A version that pooled both halves was
built and reverted on 2026-08-22; don't restore it from the scratchpad — the
declaration above is the union written down, which is a statement, where
pooling made the bus's shape depend on which readers happened to exist.

**`carolyne/uarch/o3/dispatch.py`** — **`Dispatch`** (2026-08-24), the stage
in the `Decode` shape: the bus from `build_dispatch`, its own
`dispatch_meta` `PipCon`, the two `connect()` slots (`decode`, `next_meta` —
wiring call pending), and **`transfer()`** (`@flow`) —
`pip(dispatch_meta){ zync(next_meta){ per-lane convert_lane } }`. Decision:
**the conversion is ONE k2k assign per lane** (`dispatch_entry *=
decode_entry`; `*=` because the bus rows are WIRES, a lane means something
only in the grant cycle): name+width pairing copies valid/pc/npc/uop_idx and
the operand groups, and SKIPS exactly the RENAME half — `pr_idx_<n>`,
`rob_des_idx`, `rsv_id`, `is_spec`/`spec_tag`, `is_branch`/`is_store`, plus
`data_src_1` (the bus carries data for every source; rs1 is never an
immediate, so decode has none) — Kathryn's skip warning at elaboration is the
honest list, and the unfilled wires read implicit zero until
rename/allocation lands and overlays them at its own rung. FOUND ON THE WAY:
sibling TOP-LEVEL modules share no ancestor, so `emit_verilog` panics
(`find_common_ancestor_module_paths`); stages must be constructed INSIDE one
parent module's `@init` — the shape the eventual top CPU module has anyway,
and gen/build_flow do not catch it, only emission does.

**`carolyne/uarch/o3/decode_helper.py`** — `build_decode_table(config,
name="decode")` (2026-08-22), the decoded-µop record, **one row per
`fe_lanes`**, built on the same terms as the ROB's table and a station's.
`DecodeEntryBase` states the fixed half (`valid`, `pc`, `npc`, `uop_idx`) and
the builder adds one field group per atomic operand:

| core                | fields                                            |
| ------------------- | ------------------------------------------------- |
| src                 | `active_<n>`, `valid_<n>`                         |
| src, arch class     | + `ar_idx_<n>`                                    |
| src, µtemp target   | + `data_<n>`                                      |
| dest                | `active_<n>`, `wb_required_<n>`, `ar_idx_<n>`      |

The operand set is **CORE-WIDE and BOTH DIRECTIONS** (`used_atomic_operands()`,
srcs then dests) where the ROB's is dests-only and a station's is per-unit: a
decoded µop has not been routed anywhere yet, so the record must hold whatever
it turns out to be. **NO `pr_idx` anywhere** — decode is BEFORE rename, so
`ar_idx` is what rename READS and `pr_idx` is what it ANSWERS; a physical index
in a pre-rename record would be a field nothing can fill. `active_<n>` is the
generalization of the ROB's bit to sources: the record has a slot for every
operand the ISA declares and a given µop fills only some, so `active` is what
says which. `valid_<n>` on a source means the value is ALREADY IN HAND — rename
has nothing to look up and the entry reaches its station already woken — which
is what an immediate is; it feeds the station's `valid_<n>` directly. Decision:
the kinds are asked for **conditionally**, because `operand_field` RAISES for
`ar_idx` on a core with no arch class rather than returning 0 (that is
`field_width`'s µtemp refusal, and it is what a 0-width `ar_idx` on a
one-register class is NOT — that one is skipped silently). So `ar_idx` rides on
`has_arch` and `data` on `has_imm`, which for RV32I gives src_1 no `data` (rs1
is always a register), src_2 both (rs2 OR the immediate), and src_3 no `ar_idx`
(the immediate alone). LIMIT, the open `Uop.imm` gap read from the hardware
side: `data` is built for anything that MAY name a µtemp, and a real x86 µtemp
is not known at decode but produced by an earlier µop of the same crack — the
description cannot yet tell it from an immediate, so `valid_<n>` is what the
decoder has to answer honestly per slot. The table is
`reset(valid=0, active_<n>=0)`: a lane powers up empty with no slot claimed.

**`carolyne/uarch/o3/decode.py`** — **`Decode`** (2026-08-24), the whole
stage in one Module: the table, `decode_meta`, the two `connect()` slots
(`fetch`, `next_meta` — the wiring call itself still pending), and the decode
logic as methods (a separate `laneDecoder` class held them for a day and was
MERGED in — one stage, one object). A `UopSeq` may
crack an instruction into SEVERAL µops, and decode walks them BREADTH-FIRST,
one LEVEL per cycle: **`transfer()`** (`@flow`, the name `Fetch` uses — and
`decode` is taken: `self.decode` is the TABLE) builds
`pip(decode_meta){ seq{ zync(next_meta){ per-lane guards }, … one per level } }`.
Decision: one seq child per level — a Kathryn seq child gets its own
StateNode, so a child IS a cycle — and every level is a **zync on the
consumer's arb**: its writes fire on `state & grant`, so the walk paces
itself on the handshake and needs no explicit exit. The pip holds fetch for
the whole walk (`master_ack` low mid-body), so the instr word is stable at
every level; cost, accepted: one instruction per N cycles, N = the longest
crack (RV32I: N = 1, nothing changes). A `par` per level was in the sketch
and DROPPED — it buys nothing around a single zync, and the pip body must
hold exactly one top-level child (the seq). **`group_uops_by_level(isa)`** flattens
the mop table for the walk: one path per (mop, uop_seq), guarded by EVERY
stated (field, value) rule on it — the mop's and the uop_seq's, the whole
encoding side (a template carries no matcher), the SAME conjunction at every
level so the identity cannot drift mid-crack; a half-stated matcher is
dropped, a path with no rule at all is refused; `levels[k]` holds the k-th
µop of every longer uop_seq.
**`mop_decode(level, …)`** lays one INDEPENDENT zif per path alive at the
level — parallel, no zelif chain, since the encoding table's own mutual
exclusivity makes priority redundant — with the guard built by
`match_field_bits`. **`uop_decode(uop, …)`** writes the WHOLE record for a
matched lane in ONE `|=`: valid=1, pc, npc = pc + ilen_bytes, `uop_idx` (the
template's declared id), and a field group per atomic operand, ZEROS for
slots the µop does not fill — the rows are REGs, and silence would keep the
previous instruction's claim. Decision: **matcher presence separates an
immediate from a linking µtemp** — an is_intermediate source WITH a matcher
is an immediate (valid=1, data extracted); WITHOUT one it is produced by an
earlier µop of the same crack, so valid=0, data=0, active=1 (LIMIT: nothing
wakes a linking µtemp downstream yet — that is the cracker/rename story).
**`write_lane_default`** is the no-hit half: valid=0, once per lane per
level, at **`PRI_DECODE_DEFAULT`** (`priority.py`) — the ladder's one
BELOW-user rung, because at EQUAL priority an unconditional write is emitted
after (and silently beats) every zif write; one rung down, every matched
branch beats the default and a no-hit level hands a bubble. The earlier flat
`decode_templates` design and its multi-µop refusal are SUPERSEDED by
`group_uops_by_level`; `tests/test_decode_templates.py` (untracked) still pins the
old shape and needs rewriting against `group_uops_by_level`.

**`carolyne/uarch/common/word_util.py`** (2026-08-24) — reading the word by
the description's rules. Decode is the ONE legitimate consumer (§2: nothing
downstream carries the raw word), but the helpers live in `common/` beside
`hw_util` on that package's terms: NO Kathryn import, `word` opaque — an int
under pytest, a signal under elaboration, typed `Any` on purpose (the
ExecContext bargain), while the rule parameters are real description types.
Decision: **`extract_field_bits` returns a SLICE for a one-segment field on
a signal** — a slice is a view, so the emitted Verilog is a bare part-select
with no shift/mask wires — and falls back to full-width shift-and-OR for
ints and scrambled fields, because a slice's width is the segment's own
(shifting one left for placement TRUNCATES — measured) and Kathryn has no
concat. `extract_arch_index` reads a literal index as the implicit register
and a FieldRef through the operand's matcher, refusing one without;
`extract_imm_value` is STILL the extraction-gap placeholder (naive
first-segment-lowest, no sign extension, no placement — wrong for
imm_b/imm_j; the real rule swaps in there); `match_field_bits` is the guard
half — per-segment equals, AND-ed, slice compares on signals. Names are
verb-first on purpose.

`FetchDT` is now **`FetchEntryBase`** (2026-08-23), the name every other record
in the core has (`DecodeEntryBase`, `RsvEntryBase`, `RobEntry`).

**`carolyne/uarch/o3/tag_gen.py`** — `book_rename` returns **`(is_spec, tag)`**
(2026-08-26): `is_spec` says the lane dispatches under an open speculation —
`free_tag` below full, OR an earlier lane of the same cycle booking a branch
(`_spec_before`, reading the same `branch_port[:port]` slice `_tag_after`
does, so the bit is call-order-independent like the tag). Decision: the pool
check reads the REGISTER only, never `free_tag + resolve_port` — the resolve
does NOT lead here the way `_resolve` lets it lead the free count — because
the caller STALLS rename in any cycle `on_suc_pred` fires, so a booking never
lands beside a resolve and the pre-resolve read cannot be stale. That stall is
a caller obligation, stated in the module header beside `over_use`'s. Also
2026-08-26, in `dispatch.py`: `promised_pr_idx` is now **`prf_acquisition`**,
holding `(req, pr_idx)` per `(lane, id(atm_opr))` — the `valid & active`
request bit rides beside the promised index so the update half can gate on it.
Same day: **`is_branch` joined `DecodeEntryBase`'s fixed half** — branch-ness
is DECODE's to supply, because dispatch books the speculation tag against it:
`Dispatch.warm_tag_gen` calls `book_rename(lane, valid & is_branch)` per lane
(an empty lane consumes no tag) and saves the `(is_spec, tag)` pair in
`tag_acquisition`, keyed by lane; `tag_gen` is a fourth `connect()` slot,
core-wide where `reg_arch_mng` is per-class. The 1-bit field k2k-copies onto
the bus's own `is_branch` in `convert_lane`, so it left the header's skip
list. LIMIT: `uop_decode` writes it ZERO — the description layer cannot yet
say which µop templates are branches, so no decode marks one and no tag is
ever consumed until that rule lands; the write must exist even so, because
the rows are REGs and silence would keep the previous instruction's claim.
Later the same day TagGen took the **Prf gating pattern** whole:
`rename_success_trigger` (named `rename_commit_trigger` for a day — TagGen's
pair is rename OR successful prediction, not commit), `on_rename()` firing it
from the granted scope
(dispatch's `update_tag_gen`, in the zync beside `update_prfs`),
`on_suc_pred` firing it too — Prf's `on_commit` bargain — and
`on_update_meta` became TagGen's own `@flow`, counter writes gated by
`zif(trigger)` with `over_use` computed outside the gate. The why: warm
drives the branch ports UNGATED, so without the trigger a stalled cycle
would consume tags; with it, a cycle where neither rename nor resolve acted
moves neither counter. `on_mis_pred` stays outside the chain at raised
priority, as before. Also 2026-08-26: **`wb_required_<n>` exists only on a
`DEST_W_REQ` core**, and the rule lives in **`operand_field.field_width`** —
it answers 0 for the bit on anything else, the same nothing-to-store bargain
`ar_idx` makes on a one-register class, so EVERY record built through
`operand_fields` (ROB, decode, dispatch bus, stations) drops it at once. A
first version put the conditional in `rob_operand_fields` and was moved the
same day — the caller states WHICH kinds it keeps, the one place that sizes
them decides where a kind stores nothing. `rsv_helper`'s own role conditional
collapsed into a plain dest tuple; `decode._operand_group` writes the bit
(as `active`) only where the record has it. The SEMANTICS, corrected the
same day: the bit is the per-instruction PERMISSION a `DEST_W_REQ` write
asks — a plain `DEST` stores none because its write asks none, so
`Rob._retire` gates the ARF hop on `frees & wb_required` for a DEST_W_REQ
core and on `frees` ALONE for a plain DEST (a first reading had the hop
skipped entirely there; wrong way round). FIXED BY THE CORRECTION: RV32I's
`AOPR_DEST_1` is a plain `DEST` and decode used to store the bit as
`active & is_write_required` = constant 0, so commit NEVER moved PRF→ARF —
rd's writes now retire on active alone. And `_retire` FLATTENED (same day):
one dest per architectural class is the ISA's own rule
(`_reject_shared_dest_classes`), so the per-class inner loop matched exactly
one operand — the class loop, the `frees` list, its `any_of` and
`_commit_classes` all dropped; each dest operand drives its class's
`Prf.on_commit` port directly, still one drive per lane per class.
Every `warm_*` now RETURNS a 1-bit READY (2026-08-26): availability in
ready-polarity so the caller ANDs them — `~tag_gen.over_use`,
`~prf.over_use` per class, `val(1, 1)` from `warm_rts` (registering metas
runs out of nothing), the ROB's `dispatch_fits` — collected in `transfer()`
onto the `ready_to_go` wire (`dispatch_ready_to_go`), the cycle's go/stall
bit the handshake will consume. Both over_use wires are readable at warm
time because each block's own @flow drives them outside its trigger gate.
And `warm_rob`: `rob_acquisition = rob.free_slots(self.decode)` — the
(dispatch_fits, free_idx) promise, with `rob` a fifth connect() slot.
Deliberately the DECODE rows, not the bus: the bus wires are driven inside
the granted zync, and the fit answer must exist before the grant it helps
decide. free_slots caches on `_free_built`, so `update_rob`'s
`on_dispatch(self.dispatch)` (wired same day, in the granted zync) reuses
the decode-fed wants while taking row CONTENT off the bus — wants
pre-grant, entries from the filled lane.
Then `warm_rts`: each lane registers its rename on its
class's RT via `Rt.book_rename(lane, req, is_branch, tag, ar_idx, pr_idx)` —
metas only, no hardware; req/pr_idx read back off `prf_acquisition`,
is_branch/tag off `tag_acquisition` (which now stores the TRIPLE
`(is_branch, is_spec, tag)` — the prf_acquisition move again), ar_idx off the
decode row, a one-register class passing literal 0 since it stores no
`ar_idx` field. Then **`update_rts` + the `Rt.on_rename` repair** (same day):
one `rt.on_rename()` per class inside the granted zync, and the repair came
with the caller — lane k now overlays ITS OWN `temp_dispatch` row (the old
body wrote `temp_commit[k]`, a 1-row array, out of bounds past lane 0), and a
branch snapshots `temp_dispatch[k]` AFTER its own overlay resolves
(`PRI_RENAME` beats the chain copy), which killed the drafted k==0 special
case. Post-own-rename is the deliberate choice: `on_mis_pred` restores
`spec_rt[tag]` into master while the ROB lets the branch itself retire, so
the branch's own mapping must survive the rollback — a pre-rename snapshot
would fail commit's renamed/prf_idx fixup and leak the physical register. A
port with no booking raises, naming the port.

FOUND ON THE WAY: `Rt.on_normal_flow` walked `sptag_len` rows of
`temp_dispatch`, which is `(rename_ports, amount)` — out of bounds whenever the
two differ, so NO design containing a rename table could elaborate. Fixed to
walk `rename_ports` and to feed `master_rt` from the last lane's row rather
than the commit row. `Rt.on_rename` had the same confusion between
`temp_commit` and `temp_dispatch`; repaired 2026-08-26 when `update_rts`
became its first caller — see the tag_gen/dispatch entry above.

NEXT UP — the function unit, designed 2026-08-19. Step 1 (the declared port
shape above) and step 2 (`ExecContext` + `AluUnit` + the fake-context test,
2026-08-22 — see the `exec_context.py` entry above) are done:

3. **`carolyne/uarch/o3/fu.py`** — the real context and the stage skeleton.
   Each stage of `unit.stages()` is a `pip` block chained by `zync` into the
   next, so a stage that waits simply does not reach its zync and the
   back-pressure runs up to the station, which already stalls on the unit's
   arb. That makes VARIABLE latency natural and keeps ONE completion point
   (the last stage), so two results can never collide on the writeback port.
   The engine threads the µop record down the stage registers — `rob_des_idx`,
   `pr_idx_<dest>`, and per stage `is_spec`/`spec_tag` — and owns writeback:
   `Prf.on_wb`, `Rob.on_write_back`, the bypass broadcast.
4. **Speculation is the engine's, never the ISA's.** `on_mis_pred(fix_tag)`
   calls `stage_arb[k].flush()` INSIDE a `zif` on that stage's own tag — the
   flush binds the arb reset and drives its wire in whatever scope it is
   called from, so the kill is selective. Per-stage tags are what make it
   selective: a pipeline can hold an OLDER instruction the branch never
   covered, and a blanket flush would kill it too. Clearing the grant is
   enough to suppress writeback, so the pip's own state IS the valid bit —
   no second `valid` to disagree with it. `set_reset` is set-once per arb, so
   every condition that ever kills a stage must be OR-ed into that one call.
   `on_suc_pred` masks the tag out per stage, the `RsvBase`/`Rt`/`Mpft` idiom.
5. **`mem` / `redirect` / `trap`** last, and BLOCKED on one question: what
   happens to an outstanding external request when the kill lands. Wait and
   discard, tag-and-match, or a cancel line the facility honours — a decision
   for whoever owns the `mem` contract.

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
- **Multiple drivers on one component resolve by PRIORITY, and priority IS
  emission order.** A component's update events are emitted in ascending priority
  inside one `always` block, so the LAST one wins (`reg.reset` sits at
  `DEFAULT_UE_PRI_RST`, above everything). At EQUAL priority the order is NOT the
  order the statements were written: an assignment made inside a flow block
  (`zif`) is emitted BEFORE every unconditional one. So "copy the row, then
  overlay the exception on top" only builds what it reads like if the overlay
  names a higher `priority(...)`; written plainly it produces the OPPOSITE
  hardware, silently, with no error anywhere. A layered structure (a wire row
  copied forward and then overlaid, as a rename table's stage chain is) must
  therefore state one priority per layer and rely on statement order for nothing.
- **A wire needs no `.default(0)`** — an undriven wire already falls back to an
  implicit zero at the lowest priority. (Until 2026-08-18 an explicit
  `.default(v)` was bound ABOVE user priority and therefore overrode the very
  assignments it was supposed to back up, which left `Prf`'s and `TagGen`'s
  `.default(0)` port wires reading 0 forever. Fixed in Kathryn; those two files
  are correct as written again, and new code can simply omit the call.)
- **A Karray selection collapses every dimension to exactly ONE element**, and
  every dimension must be indexed — there are no ranges, so there is no row copy
  and no whole-array assign; copying a row is a Python loop of element k2k
  assigns. A runtime-indexed (`arr[sig]`/`arr[fn]`) WRITE additionally requires a
  reg backing, because a wire cannot hold its non-selected elements. Both push the
  same way for a combinational structure: index the element statically and put the
  runtime part in the guard (`zif(req & idx == a)`), which builds the same
  hardware with the fan-out visible.
- **An augmented assign REBINDS the Python name it is written on.**
  `row |= {...}` is `row = row.__ior__(...)`, and Kathryn's assignment returns
  an internal assigned-marker, so the handle is dead afterwards: a loop that
  writes a cached row and then reads it again fails with
  `'_Assigned' object has no attribute ...`. Write through a fresh selection
  every time (`self.table[idx] |= {...}`) and keep a cached handle for READS
  only. An element accepts a `{field_name: source}` dict, which is what lets a
  loop over ISA-derived field names write without naming them statically.
- **A k2k assign pairs fields by NAME AND WIDTH**, and a destination field
  with no match in the source is SKIPPED, with a `UserWarning` naming the
  fields it dropped. So `wide_row |= narrow_row` and `narrow_row |= wide_row`
  both build, copying the overlap — which is what lets one core-wide dispatch
  lane land in a reservation station's narrower entry without an adapter. The
  warning is the only signal that something did not copy, so a field the
  destination MUST have written needs a value stated explicitly (an override in
  the same assign, never a second write at equal priority).
- **A `pip` / `zync` block must be built in an UNCONDITIONAL scope.** Nesting one
  inside a `zif` panics at the block's exit with "zero-cond-if sub blocks must
  have BasicNodeFlow join policy" — a conditional block joins differently from
  the arbitrated one. Gate the WORK inside the block, or gate the arbiter with
  `set_hold`/`set_reset`, never the block itself.
- **`Karray.reset(**field_values)`** (added to Kathryn on 2026-08-18):
  one value per field, shared by every element, recorded on each element's own
  backing register so the reset event stays the reg's. A field left out powers up
  undefined. Before it a Karray had no reset at all — fatal for any state array
  whose valid bits must start at 0 (a RAT's `renamed`; `Prf.storage.fin` still
  wants one).
- **A Karray record is finished at instantiation** (added to Kathryn on
  2026-08-16 for this project). The class body states the shape a record usually
  has; the call settles it, and the keyword's VALUE picks what it does — an
  `int` sets the width of a DECLARED field, a `kaf()` ADDS a field only that
  array has:
  `FetchEntryBase(REG, (lanes,), "fetch", pc=64, instr=16, spectag=kaf(8))`.
  `kaf()` with no width in the class body declares a field every instantiation
  must size. Added fields append after the declared ones, flatten like any
  bundle (`pos=kaf(Vec2)` → `pos_x`/`pos_y`) and read back as `d[0].spectag`.
  This is what lets the engine write each record class ONCE, size it from the
  description (`isa.pc_width`, `ilen_bytes * 8`), and let one pipeline carry a
  field another does not — before it, one shape at two widths meant a `type()`
  factory per record, because `__init_subclass__` stamps the field list when the
  class is created and a class body cannot see a caller's parameters. The class
  is never mutated, so two arrays of one class may differ. A field may not be
  named `backing`/`shape`/`name` (they are `Karray.__init__` parameters);
  declaring one raises at class creation.

## 7. Conventions

- Discuss design decisions before coding them; when a choice is made, record
  the *why* in **§4 of this file** (the design log), never in the source. A
  file's own comments stay CORE: what the code does, plus the Kathryn or
  contract rule a reader would break without. No `Decisions (date):` blocks,
  no "this was tried and reverted", no cost/benefit prose in headers or
  docstrings. (On 2026-08-19 those blocks were stripped from every file under
  `carolyne/`, −948 lines; don't reintroduce them.)
- Validate descriptions at construction (`__post_init__` raising ValueError
  with the reg-file/operand name in the message) so bad ISA specs fail
  loudly, not deep in elaboration.
- Tests double as usage documentation — e.g. `tests/test_operand.py` builds
  the x86 `add [mem], reg` cracking shape from the contract doc.
- Description types are frozen dataclasses, pure data, no Kathryn imports.
