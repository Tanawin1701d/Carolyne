# The Carolyne µop contract — draft v0.1

This document is the **normative boundary** between an ISA package
(`carolyne/isa/*`) and the generic out-of-order engine (`carolyne/uarch/`).
If a new ISA can be brought up by supplying only the deliverables in §6 —
without touching `uarch` — the contract is doing its job. Every place the two
mini-x86/RISC-V bring-ups force an edit inside `uarch` is a contract bug and
must be fixed *in the contract*, not patched in the engine.

The contract lives on two planes:

- **Elaboration plane** (Python, generate time): the ISA package hands the
  engine one `IsaDescription` object. The engine sizes and shapes itself from
  it — rename tables, decoder trees, register files, commit logic are all
  *derived*, never hand-written per ISA.
- **Hardware plane** (run time): after decode, the two sides communicate
  exclusively in **µop records**. No signal downstream of rename may encode an
  ISA-specific meaning.

---

## 1. `IsaDescription` — the elaboration-plane object model

One object, five parts. All widths/counts below are elaboration-time constants
the engine reads to size hardware.

### 1.1 Register classes (`RegClass`)

```python
RegClass(name, count, width, renamed=True, const_regs={index: value}, arch_alias=...)
```

- Each class gets its own rename table (RAT), free list, and physical
  register file — *generated per class*, so flags, GPRs, and predicates are
  all "just register classes" to the engine.
- `const_regs` marks architecturally constant registers (RISC-V `x0` → 0);
  rename bypasses them to a constant read and discards writes.
- The PC is **not** a register class; it is engine state (see §4.3).
- Litmus test for the contract: x86 `FLAGS` must be expressible as
  `RegClass("flags", count=1, width=6, renamed=True)` with **zero**
  special-casing inside `uarch`. Partial-flag writes (x86 instructions that
  update only some flags) are handled in the cracker by reading the old flags
  value as an extra source — the engine never learns about flag subsets.

### 1.2 The µop kind catalog (`UopKind`) — fixed by the contract

The catalog of operations the engine natively executes. It belongs to the
**contract**, not to any ISA; ISA semantics are *lowered onto* it.

v0.1 catalog (integer core):

| group   | kinds                                                             |
| ------- | ----------------------------------------------------------------- |
| alu     | ADD, SUB, AND, OR, XOR, SLL, SRL, SRA, SLT[U], MOV-IMM            |
| muldiv  | MUL, MULH[U/SU], DIV[U], REM[U]                                   |
| mem     | AGU (base+index·scale+disp), LOAD (size, sign), STORE (size)      |
| control | BR-COND(cond-kind), JMP, JMP-INDIRECT, CALL-LINK                  |
| system  | SERIALIZE, FENCE, TRAP(cause), READ-SPECIAL / WRITE-SPECIAL       |

- `BR-COND` takes a small `cond-kind` field (eq/ne/lt[u]/ge[u]/flag-test) so
  both RISC-V compare-and-branch and x86 flag-test branches lower to one kind.
- **Escape hatch — custom function units**: an ISA may declare
  `CustomFu(name, kinds, latency, ports)` in its description; the engine
  instantiates it and routes the declared kinds to it. This is the mechanism
  that makes the "ISA researchers experiment for free" pitch real: a new
  instruction = a cracker entry + (at most) a custom FU, still zero `uarch`
  edits.

### 1.3 Encodings and instruction length

- Encoding table: per instruction, a match/mask pair over the instruction
  bytes plus named field extractors (rd/rs/imm/modrm…). The decoder tree is
  *generated* from this table (Kathryn `pick`/`zcase` over match/mask).
- **Length pre-decode**: the ISA supplies `ilen(first_bytes) -> length`, a
  pure function on the first `max_prefix_bytes` bytes. Fixed-length ISAs
  return a constant, and the fetch aligner degenerates to the simple fast
  path. Mini-x86's `ilen` reads opcode + ModR/M. This function is the *only*
  variable-length support the engine provides; anything not decidable from
  the declared prefix window is out of contract (rules out full x86 prefix
  soup — deliberately, see §7).

### 1.4 Crackers (instruction → µop template)

Each instruction lowers to a **linear sequence of 1..N µop templates** (v0.1
restriction: a sequence, not a DAG — see open question Q3) over:

- architectural registers (by class + extracted field),
- immediates (extracted fields),
- **µtemp registers**: a contract-provided `TempRegClass` for
  intra-instruction values (e.g. x86 `add [mem], reg` → AGU→t0, LOAD t0→t1,
  ADD t1,reg→t2, STORE t2). µtemps are renamed like any class and are dead at
  the instruction boundary by construction.
- Each template is stamped `first`/`last` so the engine knows instruction
  boundaries (§4.4).

### 1.5 Trap policy

v0.1 keeps this minimal: precise traps at commit. The ISA supplies, per trap
cause, a handler-entry sequence expressed *as µops* (write special regs, jump
to vector). The engine's only primitives are: flush-younger, redirect-fetch,
run-this-µop-sequence. No virtual memory, no privilege modes in v0.1.

---

## 2. The µop record — the hardware-plane format

Field widths are derived from the `IsaDescription` at elaboration time
(`log2` of catalog/class/count sizes). The record is what flows through
rename → dispatch → issue → execute → commit; it is the *entire* run-time
vocabulary between front-end and engine.

| field                  | width derived from                          | notes                                     |
| ---------------------- | ------------------------------------------- | ----------------------------------------- |
| `kind`                 | µop kind catalog + declared custom FUs      |                                           |
| `src[0..2]`            | class-id ⊕ max arch index over classes      | 3rd source: store data / old-flags read   |
| `dest[0..1]`           | same                                        | 2nd dest: flags write (x86), link reg     |
| `imm`                  | max immediate width over encoding table     |                                           |
| `mem`                  | fixed small                                 | size, sign-extend; only on AGU/LOAD/STORE |
| `br`                   | fixed small                                 | cond-kind, is-call/is-ret hint            |
| `bound`                | 2 bits                                      | first/last µop of its instruction         |
| `serialize`            | 1 bit                                       | drain-before, from cracker                |
| `pc`, `pred`           | engine-owned                                | attached by fetch, opaque to the ISA side |

Design rule: **no ISA bits ride along**. If an ISA needs information at
execute time, it must be expressible in the fields above (or in a declared
custom-FU kind). The moment a "raw opcode" field sneaks into the record, the
separation is dead.

---

## 3. Front-end ownership

The decode/crack stage is *generated* by the engine from the encoding table +
crackers, so the ISA package contains **no Kathryn code at all** — it is pure
description (tables + tiny pure functions). This keeps the effort metric
honest: ISA package lines ≈ spec lines, not hardware lines.

Pipeline: fetch → length-align (§1.3) → match/mask decode → template expand →
µop queue. Multi-µop expansion stalls fetch, it does not widen rename.

---

## 4. What the engine derives (elaboration-time adaptation)

This section is descriptive (the engine's job), listed here so contract
changes are checked against it.

### 4.1 Rename
Per renamed `RegClass`: RAT (Kathryn `Karray`), free list, physical register
file sized `count + rob_depth` (tunable), constant-register bypass.

### 4.2 Issue/execute
FU pool = standard units + declared `CustomFu`s; issue-port binding computed
from kind→FU mapping. Standard OoO machinery (wakeup/select via `Arb`,
bypass network) is ISA-blind.

### 4.3 Control flow
PC, branch prediction, and redirect are engine-owned. The ISA influences them
only via `br` fields and `ilen` (for sequential-PC computation).

### 4.4 Commit
ROB retires at **instruction** granularity using `bound`: a multi-µop
instruction commits all-or-nothing (x86 memory-op atomicity w.r.t. traps),
which also gives precise traps for free on RISC-V.

---

## 5. RV32I vs mini-x86 — the contract exercised

| contract concept   | RV32I                          | mini-x86 (scoped subset)                 |
| ------------------ | ------------------------------ | ---------------------------------------- |
| register classes   | X(32×32, x0 const)             | GPR(8×32), FLAGS(1×6)                    |
| `ilen`             | constant 4                     | opcode+ModR/M window                     |
| cracking           | 1 µop nearly always            | 1–4 µops (mem operands via µtemps)       |
| branches           | BR-COND(cmp-kind, rs1, rs2)    | BR-COND(flag-test, flags-src)            |
| flags              | — (class absent)               | 2nd dest + old-flags 3rd src             |
| second dest        | JAL link (or cracked)          | flags write                              |
| traps              | ecall/ebreak/illegal           | int3/ud2/div-zero                        |

Mini-x86 v0.1 scope (freeze early, resist growth): 32-bit flat memory model
only, ~20 integer instructions (mov/add/sub/and/or/xor/cmp/test/inc/dec/
push/pop/jcc/jmp/call/ret/lea), ModR/M with base+disp (index·scale stretch),
no prefixes, no segmentation, no string ops, no FP.

---

## 6. Deliverables checklist for a new ISA (the effort metric)

An ISA package supplies exactly:

1. register classes (§1.1)
2. encoding table (§1.3)
3. `ilen` (§1.3) — constant for fixed-length ISAs
4. crackers: per-instruction µop templates (§1.4)
5. trap policy sequences (§1.5)
6. *(optional)* custom FU declarations (§1.2)

Everything else is generated. "Lines in 1–6" vs "lines in `uarch`" is the
headline number for the paper.

---

## 7. Out of scope for v0.1

Virtual memory / privilege modes, interrupts (traps only), FP, multicore
memory models (single core, in-order commit of memory), full x86 prefix
decoding, RVC (noted as a cheap *second* variable-length demo via `ilen` —
good stretch goal for the paper).

---

## 8. Open questions

- **Q1 — PRF organization**: per-class physical register files (simple,
  matches per-class RAT) vs unified PRF with class-tagged tags (better area).
  v0.1 leaning: per-class, revisit after first synthesis numbers.
- **Q2 — AGU fusion**: separate AGU µop (uniform, matches µtemp story) vs
  fused load-with-addressing (fewer µops, x86-friendlier). v0.1 leaning:
  separate AGU; measure the IPC cost on mini-x86.
- **Q3 — template expressivity**: is a linear µop sequence enough, or do
  crackers need DAGs? Linear is enough for the v0.1 instruction set; DAG
  support would only change the cracker format, not the record — safe to
  defer.
- **Q4 — aspect 2 (component interface)**: memory port + control/debug
  interface of the generated core as a reusable Kathryn block. Deliberately a
  separate design doc; nothing in this contract may depend on it.
