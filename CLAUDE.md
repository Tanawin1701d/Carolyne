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
  → field) and *raises* if the core does not carry it; `has_arch`/`has_temp`
  say what is on offer. Decision: it carries **no `width`, `is_arch`,
  `is_intermediate`** (ambiguous with two candidates — only the selection
  answers them) and **no `is_const`/`is_decoded`** (facts about the *index*,
  which the core has not got). It owns `OperandRole`
  (`SRC`/`DEST`/`DEST_W_REQ`) and `TargetKind` (`ARCH`/`TEMP`), so the import
  runs `operand` → `atomic_operand` one-way. Decision (2026-08-19): a **`name`**
  joined, optional and defaulting to `""`, validated as a Python identifier —
  it is the STEM of every hardware field a consumer builds for that slot
  (`valid_<name>`, `pr_idx_<name>`, `data_<name>`, `required_<name>`), so a
  core with no name simply cannot be turned into hardware and the block that
  needs one says so (`rsv.station_cores`). Optional, not required: 58
  construction sites exist and a core is a legal description object without a
  name; `IsaBase` enforces uniqueness across the ISA for the ones that have
  one. Decision (2026-08-19): **`DEST_W_REQ`** is the third role — a
  destination whose write is REQUIRED before the instruction retires, which a
  reservation station tracks with a `required_` bit where a plain `DEST`
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
- **`IsaBase(name, pc_width, pc_align, ilen_bytes, reg_files, atomic_operands,
  operands, ops, exec_units, uops, mops)`** (`isa.py`) — the
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
  `used_ops()`, `used_reg_files()`, `used_uops()`, `used_operands()`,
  `used_atomic_operands()`. Decision (2026-08-19): **`src_atomic_operands_for(unit)`
  / `dest_atomic_operands_for(unit)`** read `units_for()` the long way round —
  unit → its ops → the µops some mop cracks to → their slots → the cores —
  because the elaborator building ONE FU has to size that unit's operand ports
  and the container could only answer the question the other way. Two public
  halves over one private `_atomic_operands_for(unit, roles)`, because src
  cores size READ ports and dest cores size WRITE ports; the halves are
  disjoint by construction, since role lives in the core and `Uop` cross-checks
  it against slot position. It walks what the MOPS reach, not the declared
  `uops`; ops match by VALUE so a unit built from a fresh `Op("ADD")` still
  matches, everything below by identity. An undeclared unit is not rejected
  (neither is `units_for`'s op) but a non-`ExecUnit` is, pointing at
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
drafted and deleted), `op.py` (its own op vocabulary + `exec_units()` — no
shipped catalog), `field_match.py` (32-bit field positions, the addressing group
`PC_WIDTH = X_LEN` / `PC_ALIGN = 4` / `ILEN_BYTES = 4` that `Rv32i` names as its
three scalar defaults,
and `FORMATS` = the six base formats R/I/S/B/U/J as `union`s of those fields,
each tiling the word exactly once — declared but not yet consumed, since a
`Mop` has no format slot), `uop.py` (`UOP_*` + `UOPS`), `mop.py` (`MOP_*` +
`MOP_TABLE` → 11 opcode-group `Mop`s, exhaustive over `UOPS`), `rv32i.py`
(`Rv32i`, an `IsaBase` **subclass** supplying every vocabulary as a field
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

**`carolyne/uarch/o3/rsv_helper.py`** — `build_rsv_table(config, rsv_spec, name="")`
builds ONE reservation station's entry table (2026-08-19). `RsvEntryBase`
states the shape every station has (`valid`, `is_spec`, `spec_tag`, `uop_idx`,
`pc`); `RsvO3Entry` adds the age track and `RsvIOREntry` adds nothing, since
position in an in-order station IS the order. The builder adds the part that
varies with the ISA: one field group per `AtomicOperand` the station's units
read or write, named after the core —

| core                    | fields                                  |
| ----------------------- | --------------------------------------- |
| src on a register class | `valid_<n>`, `pr_idx_<n>`, `data_<n>`   |
| src on a µtemp only     | `data_<n>` only                         |
| `DEST`                  | `pr_idx_<n>`                            |
| `DEST_W_REQ`            | `required_<n>`, `pr_idx_<n>`            |

A µtemp source gets data ALONE because there is no PRF entry to wake on — the
value rides with the µop (RV32I's immediates are exactly this, via
`ImmTarget`). A core offering BOTH targets is sized off the arch one: `pr_idx`
from `config.phy_idx_width(reg_file)`, `data` from the class width. A µtemp
DESTINATION *raises* — the config sizes a physical file per register CLASS, so
there is no index width for one, and x86's AGU will surface that gap the day it
lands. Decision: the signature takes the **config**, not just the `RsvSpec` —
`spec_tag`, `pc` and `uop_idx` cannot be sized from a spec that holds only
size + units. `uop_idx` is `CPUO3_Config.uop_idx_width` =
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
to one unit. A lane says who it is for: `rsv_helper.build_rsv_dispatch()` gives
the bus an **added** `rsv_id` field — added, not stored, because the station
answers it on the way in and has nothing to remember afterwards — and
`lane_targets_me()` is the check. `free_slots()` hands each port a DIFFERENT
entry, which is what lets two lanes land in one cycle.

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
`AR_IDX`, `REQUIRED`, `ACTIVE`) and the width rules live here and a caller
passes the kinds it wants: a station's source is `(VALID, PR_IDX, DATA)` — or
`(DATA,)` on a µtemp — its destination `(REQUIRED, PR_IDX)` or `(PR_IDX,)`, and
the ROB's `(ACTIVE, REQUIRED, PR_IDX, AR_IDX)`. A width of ZERO means "nothing
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

| field            | width                            | what it is                |
| ---------------- | -------------------------------- | ------------------------- |
| `active_<n>`     | 1                                | this instruction writes it |
| `required_<n>`   | 1                                | the write must land first  |
| `pr_idx_<n>`     | `config.phy_idx_width(reg_file)`  | rename's physical register |
| `ar_idx_<n>`     | `reg_file.index_width`            | the architectural register |

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
  `FetchDT(REG, (lanes,), "fetch", pc=64, instr=16, spectag=kaf(8))`.
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
