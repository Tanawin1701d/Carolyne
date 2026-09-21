# Open items

Every known gap in one place: what is missing, where it lives, and what would
close it. A `LIMIT:` marker in the source is the same fact stated at the point
a reader meets it — this file is the index, the code is the record.

Scope: things that are DELIBERATELY unfinished. A bug goes in the tracker, not
here; a decision already made and recorded goes in CLAUDE.md §4, not here.

---

## Load / store

- [ ] **A misaligned access reads or writes the wrong word.** Naturally
      aligned accesses are correct as written: `LW`/`SW` at a 4-byte address,
      `LH`/`LHU`/`SH` at a 2-byte one, `LB`/`LBU`/`SB` at any address. The low
      two address bits are NOT discarded — they select the byte
      (`byte_bit_off`) or the halfword (`half_bit_off`) inside the word.
      What is missing is the access that SPANS two words: `LW` at `0x2`
      returns the word at `0x0`, and for `LH`/`LHU`/`SH` only address bit 1
      reaches `half_bit_off`, so `0x1` reads as `0x0` and `0x3` as `0x2`.
      The store direction is worse than the load one: `SW` at `0x2`
      overwrites the word at `0x0`, so a misaligned store changes bytes no
      instruction named. RV32I permits an implementation to SUPPORT
      misaligned accesses or to RAISE an address-misaligned exception —
      silently-wrong data is neither.
      *Where:* `isa/riscv/exec_unit_ls.py` (`_address_stage`).
      *Status:* TODO, deferred on purpose — until this closes, software must
      keep every access naturally aligned.
      *Closes when:* either a misalignment detect that traps (blocked on trap
      policy), or a two-word read + concatenate for spanning accesses.

---

## Memory

- [ ] **EasyMem's bank routing is unreviewed and never simulated.** The bank
      became part of the address on 2026-09-09 and every bank became dual
      port (1R1W) on 2026-09-10, so the memory now routes: each bank's read
      port takes its index from the lowest-numbered read that named it, its
      write port from the one writer, and a read that loses a contested bank
      reports `valid = 0`. Writes gained an `enable`, because a memory that
      routes a write cannot tell from the data wire alone that one happened.
      The whole machine ELABORATES and `iverilog` compiles it at 1, 2 and 4
      lanes, and every test passes — but every one of those is an elaboration
      test. **No cycle of this has ever run.** Nothing has shown that a port
      reads the bank it named, that the conflict priority is the one intended,
      or that a routed write lands in the right bank.
      *Where:* `uarch/mem/easy_mem.py` (`route_access` and its helpers), with
      `uarch/mem/common/mem_port.py` (`bind_byte_addr`, the write `enable`).
      *Status:* TODO — the design was agreed, the code is not reviewed.
      *Closes when:* someone reads it, and a simulation drives two ports at one
      bank and checks the winner's data and the loser's `valid`.
      *Update 2026-09-10:* the debugger has now run it. Two lanes fetching
      through two banks read the right words for 2 000 cycles of `hello.c`
      (`generated/debug/hello/trace.sl`), so the read routing works for the
      no-conflict case. The conflict case and the store routing are still
      unchecked.
      *Update 2026-09-15:* the STORE routing is now exercised too — `hello.c`
      under `examples/sim/rv_sim` drives the write port to three different I/O
      words and every character and integer it printed came out on the door
      the program named. Still unchecked: a contested bank, which two lanes
      fetching consecutive words can never produce.

---

## Squash recovery — CLOSED 2026-09-11

The flushed pips stayed dead because Kathryn's `pip(auto_restart=True)` fed
the flush as Start into the combinational entrance while its latches took the
same wire as reset, and RST outranks SET. Fixed in Kathryn2
(`src/model/flow_block/common/pip_schematic.rs`: the Start now SETS the wait
state at the INT priority), pinned by `test/model/tc42_pip_auto_restart.py`.
`hello.c` passes the first mispredict with one bubble cycle; what it hit
next is below.

---

## Speculation — CLOSED 2026-09-15 by the rv_sim campaign

Both items below were found by the 2026-09-11 recorder and CLOSED by running
`hello.c` under `examples/sim/rv_sim`. Neither root cause was what the symptom
suggested; the evidence is the cycle log each entry names.

- [x] **The core had no redirect path at all** — CLOSED 2026-09-15. The symptom
      was recorded as "`jal ra,98` at `0x88` redirects to `0xa8`, twice its
      offset". It is not an immediate bug: `imm_j` emits
      `WIRE_out_j[10:1] <= REG_word[30:21]`, exactly right, and
      `tests/test_imm.py` already covered it. `Fetch.override_pc` simply HAD NO
      CALLER: a squash flushed the front end and left the pc wherever the wrong
      path had run to, and `0xa8` was where fetch happened to be. Fixed by
      `declare_mis_pred(dyn_cond, next_pc)` — the ISA body states the pc
      execution continues at, since only it knows — routed through
      `CoreO3.on_mis_pred` to `Fetch.on_mis_pred(new_pc)`, which writes the pc
      at `PRI_MIS_PRED` so the redirect beats the stage's own advance.
      Pinned by `tests/test_redirect.py`. MEASURED: the commit after `0x88`
      became `0x98`, and the first character of the string printed.
- [x] **The ROB's used-entry count only moved on a dispatching cycle** —
      CLOSED 2026-09-15, and this is what made a drained branch's rollback look
      like the culprit. `Rob.on_update_meta` was called from `on_dispatch`,
      which `Dispatch.update_rsvs` runs INSIDE its granted zync, so a commit
      made in a cycle the front end did not dispatch was never subtracted. The
      log showed `alloc 11, com 11, used 1` — pointers equal (empty) against a
      count of one — and commit then retired three wrong-path instructions
      (`0xb8`, `0xbc`, `0xc0`) that the rollback had already dropped. Fixed by
      making the count the ROB's own unconditional `@flow`
      (`Rob.run_update_meta`); both ports are wires that read 0 when their side
      did nothing, so an idle cycle adds and subtracts nothing.
      Pinned by `tests/test_rob_count.py`.
- [x] **A µop carried the tag the NEXT branch would allocate** — CLOSED
      2026-09-15. `TagGen.book_rename` handed every lane `next_tag`, so the
      instructions after a branch sat under a tag no branch owned: the branch
      squashed with `0b00010` while its own wrong-path stores carried
      `0b00100`, the Mpft column read 0, and the store buffer wrote those
      stores to memory anyway — `putchar` landed on the `putint` door. Fixed by
      `TagGen._tag_in_force`: a lane carries the speculation IN FORCE, which for
      a branch is the one it opens, so a branch and everything it covers carry
      ONE value and a squash is a mask again.
      Pinned by `tests/test_spec_tag.py`.
- [x] **The store buffer's resolve guard read the wire it drives** — CLOSED
      2026-09-15. `StoreBuf.on_suc_pred` guarded the `spec_overrider` write on
      `spec_overrider` itself, a combinational loop. It was harmless only while
      the tags never matched; once they did, Verilator refused the design
      ("Active region did not converge"). Fixed with `push_pair`, the pair as
      the caller stated it, which the guard reads instead — the shape
      `ExecUnitO3.on_suc_pred` already documents.
      Pinned by `tests/test_store_buf_resolve.py`.

- [x] **Fetch took ANY grant where it needed EVERY one** — CLOSED 2026-09-15.
      `Fetch.transfer` zyncs on a LIST of arbiters (decode's, and one per
      instruction memory port) and the default `mode="any"` ORs their grants,
      so the memory answering was enough to capture a new group whether or not
      decode had taken the previous one. Decode and dispatch each bind a single
      arbiter, where the modes coincide, which is why fetch alone lost
      instructions. `mode="all"` is the fix, and with it `hello.c` printed its
      whole expected output for the first time.
- [x] **The rename table never dropped a mapping** — CLOSED 2026-09-15.
      `renamed` was set by `on_rename` and cleared nowhere: `Rt.on_commit`
      wrote the physical index back over itself, and the loop repairing the
      speculative snapshots indexed plane 0 every time instead of the loop
      variable. Every register stayed renamed forever, so once the physical
      pool wrapped, a reader waited on a writeback that was not coming — the
      `ret` ending main never issued. The clear is now clocked-only, guarded on
      what the rename chain is about to write.
      Pinned by `tests/test_rt_commit.py`.

- [ ] **A µop carries ONE tag, so a nested speculation is lost when the inner
      one resolves.** `on_suc_pred` masks the resolved tag to 0, and an entry
      under branch B2 (itself under B1) then records no speculation at all,
      although B1 is still open. Not reached by `hello.c`, which never has two
      branches in flight.
      *Where:* `uarch/o3/rsv.py`, `store_buf.py`, `exec_unit.py` (`on_suc_pred`).
      *Closes when:* an entry falls back to the next-outer open tag on a
      resolve, or the record carries the mask rather than one tag.

## The M extension

- [ ] **The multiply/divide unit is elaborated, not simulated.** `MulDivExecUnit`
      (`carolyne/isa/riscv/exec_unit_muldiv.py`) emits and compiles, and its
      µops decode; no program has yet run a `mul` or a `div` through the core.
      *Closes when:* a C program with a volatile multiply and a signed divide
      (INT_MIN / -1, a divisor of zero) prints the spec's answers in simulation.
- [ ] **The divider is combinational.** A 32-bit `/` and `%` in one stage is
      the longest path in the core; the in-order `muldiv` station keeps it off
      the ALUs but not off fmax. A sequential (restoring) divider looping in
      its stage is the replacement.
      *Where:* `carolyne/isa/riscv/exec_unit_muldiv.py`.

## Compile tool

- [ ] **MIPS32 is built, not verified, and not yet compiled here.** `mips32`
      is a target (`examples/compile_tool/target.py`) with no
      `carolyne/isa/mips` description behind it, so `verify` is skipped with
      a report that says so; the flags, `crt0_mips.S` and the linker script
      are untested until `gcc-mipsel-linux-gnu` is installed.
      *Where:* `examples/compile_tool/target.py` (`MIPS32`), `runtime/crt0_mips.S`.
      *Closes when:* the compiler is installed and `test_a_mips_program_builds_and_is_not_verified`
      runs; a MIPS description (branch-delay slots against the µop contract)
      is its own bring-up.

## The store pushed in a squash cycle — CLOSED 2026-09-17

- [x] **A store pushed in a squash cycle kept its row and lost its slot.**
      CLOSED 2026-09-17. `StoreBuf.on_mis_pred` recomputes `alloc_ptr` as
      `ret_ptr + popcount(survivors)` at `PRI_MIS_PRED`, which OUTRANKS
      `on_new_entry`'s `alloc_ptr + 1` — and the survivor count is taken from
      the table's pre-clock contents, so the entry landing in that very cycle
      is invisible to it. The row write landed (a non-speculative store is not
      cleared by the squash); the pointer did not move; the NEXT store then
      overwrote that row. MEASURED on `riscv_temp.c` before the fix: `A` is
      pushed at cycle 29 into row 0 while `exu2_control` declares a mispredict
      in the same cycle; at cycle 30 row 1 holds `B` but `alloc` is still 1; at
      cycle 32 the exit store overwrites `B` in row 1 and only then does
      `alloc` reach 2. Three stores retired, one word reached memory, and
      `com_ptr` ran past `alloc_ptr` (`a:2 c:3 r:1`).
      Fixed by the file's own idiom: a push STATES itself on a `pushing` wire,
      the way `spec_overrider` already states the tag the row will take, and
      `on_mis_pred` counts it (or clears its row when the squash covers it).
      MEASURED after: `riscv_temp` exits in 34 cycles and `hello.c` in 242,
      both matching their host builds — the first clean exits this core has
      produced. Pinned by the existing store-buffer tests; 422 pass.

      *The original entry, kept for the record:*

- [x] ~~A store retires without ever having pushed its buffer entry, and the
      store buffer's commit pointer then overruns its allocation pointer.~~
      MEASURED on `hello.c` (2026-09-15, `generated/sim/rv_sim/hello_end`): the
      branch complex declared a mispredict in the same cycle the load/store
      unit pushed, the mem station issued `SW rob:4` in two consecutive cycles,
      and one entry covered two store instructions — buffer slot 28 held the
      address AND data of the store BEFORE it (`@1020 = 0x0a` where
      `@1021 = 0x10` belonged). Two commits then advanced `com_ptr` past
      `alloc_ptr` (`a:29 c:30`), so the exit store pushed afterwards sat with
      `complete = 0` forever and the machine parked in `_park` until the
      watchdog.
      Console: `hello from carolyne\n0\n1\n4\n9\n` then one wrong byte
      instead of `16`, with everything else correct.
      *Where:* `uarch/o3/store_buf.py` (`on_new_entry` vs `on_mis_pred` in one
      cycle; `on_commit` advancing with no entry), `uarch/o3/rsv_ior.py` (the
      station re-issuing the same head across a squash),
      `isa/riscv/exec_unit_ls.py` (the push is inside stage 0's zync).
      *Status:* the entry pushed in the squash cycle is written at the edge,
      while `on_mis_pred` kills by reading the table's CURRENT contents, so it
      cannot see the entry landing beside it — the same race
      `spec_overrider` solves for the tag, not solved for the push itself.
      THE SHARPEST CLUE, and where to start: `alloc_ptr` stepped 28 -> 29 in a
      cycle with NO execution stage running at all (the log's EXEC column was
      empty), so an entry was allocated without a store executing. Check what
      gates `on_new_entry`'s two writes when the load/store unit's stage 0 is
      not granted.
      *Closes when:* a store pushed in a squash cycle is killed or never
      pushed, `com_ptr` can never pass `alloc_ptr`, and `hello.c` stops on its
      exit door with code 0.

      *Update 2026-09-16 — eleven RIDECORE programs, and two much smaller
      reproducers than `hello.c`.* The C++ Kathryn's ridecore test apps were
      ported to `examples/compile_tool/programs/` (the algorithms unchanged;
      only the three MMIO doors became the four `carolyne_io.h` calls, so a host
      build is the oracle). ALL eleven fail, and they fail in the same place.
      Two are worth keeping as the reproducers:
      - **`riscv_temp.c` — the minimal LOST STORE.** Its whole body is
        `print_char('A'); print_char('B'); finish(0);`. The machine prints `A`
        and loses both stores after it, then goes idle at cycle 2031. Two
        stores, no recursion, no branch worth speculating on: the smallest case
        that shows a store going missing.
      - **`tarai.c` (28 lines) — the DEADLOCK, with the pointers to prove it.**
        MEASURED at the stall (`--log`, cycle 3210,
        `generated/sim/rv_sim/rc_tarai_log/trace.sl`): the store buffer reads
        `a:5 c:17 r:5` — **`com_ptr` is TWELVE entries past `alloc_ptr`** — and
        every one of the 32 entries reads `cpt:0`, so `ret_ptr` can never
        advance off a head that was never completed. With the buffer jammed the
        ROB fills behind it (`a:14 c:24 u:22`, head `E:24/f:0` waiting on a
        writeback that cannot come), fetch reads HELD, and nothing moves again.
        The program never reaches its first print, which is why it and every
        other recursive program (`fib`, `acker`, `hanoi`, `sort_3`, `komachi`)
        print NOTHING AT ALL: they fill the 32-entry buffer with stack traffic
        before the first `print_char`.
      So the failure is not rare and not specific to `hello.c`'s branch mix: any
      program with enough store traffic reaches it. The programs that do emit a
      few characters first (`riscv_temp`, `stirling`, `combinat`, `stencil`) are
      the ones whose first output comes before much stack traffic.
      SEPARATE, and possibly a second bug: **`stencil.c` prints WRONG VALUES**
      rather than losing them — `08083300,00003000,080813C3,…` where the host
      says `0000002B,00000022,00000023,…`. Wrong data, not missing data, so it
      may not be this item at all.
      *Repro:* `python -m examples.sim run
      examples/compile_tool/programs/tarai.c --log --window 60 --max-cycles 6000`

---

## A value is wrong under real recursion (found 2026-09-17)

- [ ] **With the store buffer fixed, programs that really recurse still compute
      WRONG VALUES** — not missing stores, wrong data. This is a second bug and
      it is what the remaining RIDECORE failures are.
      *Reproducer, ten lines:* `examples/compile_tool/programs/rec.c` built at
      **-O0** (at -O2 GCC folds the constant arguments and the bug hides):
      `sum_to(1), sum_to(2), sum_to(5)` should print `1 3 15`, and the machine
      prints `1\x1c205\x1c`. The first value is right; then `print_char(' ')`
      emits 0x1c where 0x20 was passed, and the program's exit code is
      **0x10000020** — the MMIO base with 0x20 in it, so an ADDRESS is reaching
      a value register.
      *Not the load path:* `ldst.c` (store four words to a global array, read
      them back) is exact, and `hello.c`, `riscv_temp.c` and `rec.c` at -O2 all
      match their host builds. What the failures share is a real call frame:
      `ra`/`s0` saved and restored across a call.
      *Where to start:* the register rename around `jal`/`jalr` link writes
      (`isa/riscv/exec_unit_br.py`'s gated `wb_reg`), and the LS unit's
      sub-word path (`exec_unit_ls.py`) — 0x20 -> 0x1c is a low-bit corruption,
      not a whole-word swap.
      *NARROWED 2026-09-17 — it is TWO bugs, and `--lanes 1` separates them.*
      On `fwd.c` (12 lines: word store/load, then byte store/load) at -O0:
      - **lanes 2** fails at byte 2: the word case is already wrong. The store
        `sw a4,0(a5)` at pc 0x130 carries `a4 = 34` in a physical register that
        reads correctly (p61), yet its buffer row RETIRES with `0x11e` — a
        value that does not exist until two cycles LATER (p63, the load that
        follows). So the row's DATA is overwritten after it is pushed, and
        `exu2_control` declares a mispredict in the very cycle that store is in
        flight. The push-in-a-squash-cycle fix above is necessary but NOT
        sufficient: something in the squash path still hands out a row that is
        still live.
      - **lanes 1** gets the word case RIGHT (`1734`) and still fails on
        `print_char`, so that half is independent of fetch width.
      - **The `print_char` half is exactly MINUS FOUR, every time**: `' '`
        (0x20) arrives as 0x1c, `'|'` (0x7c) as 0x78, `'\n'` (10) as 6. It is
        the value, not the address: the byte lands in the right word at the
        right offset. `print_char(char)` at -O0 spills with `sb` and reads back
        with `lbu`, which no int-sized test exercises — `print_int(124)` in the
        same program is CORRECT.
      *Reproducers, smallest first:* `m4.c` (six calls, 175 cycles, shows the
      -4 alone at `--lanes 1`), `fwd.c` (12 lines, 150 cycles, shows both),
      `subword.c`, `rec.c`, `ldst.c` (the control: int store/load, passes).
      *HALF CLOSED 2026-09-17 — the -4 was the ZERO REGISTER.* `ret` is
      `jalr x0, 0(ra)` and books a rename for x0 like any other write, so the
      RT marked x0 renamed and later reads took the PRF (holding the discarded
      link) instead of the Arf's const mux. `addi a0,x0,32` read src_1 as
      0x000000fc — the link of the `ret` at 0xf8 — and computed 0x11c, whose
      low byte 0x1c is what `print_char` printed. Fixed in `Dispatch.warm_rts`:
      a dest naming a const register books no rename. `const_regs` had always
      said "bypasses reads, discards writes"; only the read half existed.
      *STILL OPEN, and it is now TWO separate things:*
      - **Two-lane dispatch — CLOSED 2026-09-17.** `Prf.on_rename` cleared the
        allocated entry's `fin` at the edge while `rename_src_operand` read it
        combinationally, so lane 1 consuming a register lane 0 had just
        allocated saw the previous owner's `fin=1` and stale data. Fixed by
        overriding the PRF read view at PRI_RENAME, the shape `on_wb` uses.
      - **A live physical register is reallocated — CLOSED 2026-09-17, and it
        was THREE defects stacked.** (1) `Prf`/`TagGen` counters consumed the
        warm-driven ASK wires under a trigger a commit/resolve can fire alone,
        so a stalled bundle's asks were counted: `free_entry` underflowed
        (1 - 2 = 127 on a 64-entry file) and tags leaked to `tag f:0`. Fixed
        by the `rename_landed` wire: judge over-use on the ask, move the
        counters by `req & landed`. (2) Stale µops still mid-pipe after a
        squash could report: every api effect site now gates on
        `Rob.entry_is_live` (the resolve, the fin, the writeback, the store
        push). (3) The deadlock's root: a branch snapshotting in the same
        cycle a mapping retires recorded the dropped rename (the copy at
        PRI_RENAME outranked the repair at PRI_COMMIT), and a later restore
        resurrected it — every reader of that arch register then read or
        waited on a RECYCLED physical register. Fixed by `Rt.commit_drops` +
        the `PRI_SNAPSHOT_FIX` rung: the drop lands on top of the copy.
        Pinned by `tests/test_rt_snapshot_fix.py`; the end-to-end pin is the
        RIDECORE set itself: ALL 17 programs match their host builds at the
        default two lanes and stop on their exit door with code 0 — komachi
        at 6,097,536 cycles, cprime at 396,111 on `--dmem 16384` (its sieve
        overflows the default 4 KB data memory AT LINK TIME, a program-size
        fact, not a core bug) — and the thirteen fast ones match at -O0 too.
      *Closes when:* all thirteen programs match their host builds at the
      default two lanes.
      *Repro:* `python -m examples.sim run
      examples/compile_tool/programs/rec.c --opt=-O0 --no-log`

## Kathryn handshake (found by the debug probes, 2026-09-14)

- [ ] **A parked zync does not back-pressure the stage upstream of it.**
      A pip's entrance re-arms off its own zync's STATE node — the request
      HOLDER, set when the zync is entered and held while it waits — rather
      than off the zync's grant. So while a stage's zync waits, the stage is
      re-entered every cycle and its writes land on top of data the consumer
      has not taken.
      PROVEN ON THE REAL CORE 2026-09-15, not only on the toy: running
      `hello.c`, decode still held the instruction pair `(0xe0, 0xe4)` when
      fetch overwrote its own record with `(0xf0, 0xf4)`. The pair
      `(0xe8, 0xec)` — `li a4,16` and the store that prints it — was destroyed
      and never executed, so the program's last `print_int(16)` never happened.
      Every stage of the O3 core (fetch -> decode -> dispatch) has this shape.
      *Where:* `Kathryn2/src/model/flow_block/common/pip_schematic.rs` (step 6 of
      `build`: `add_depend_node_to_ncp(pseudo_i, sub_wrap.get_exit_node_i(), None)`,
      where `pseudo` is also the arb's master-ack), and
      `zync_schematic.rs`, whose NodeWrap exit IS its state node while the node
      that fires on the grant is a separate work node.
      *Status:* FIXED IN KATHRYN2 2026-09-15 through the pair skill — a zync's
      NodeWrap exit is now a done node (`state & grant`) instead of its state
      node, so every parent block advances on completion; pinned by
      `Kathryn2/test/model/tc43_pip_zync_backpressure.py`, which reproduces
      this symptom before the fix. NOT COMMITTED there.
      CAUTION, and the reason this entry stays open here: the rebuilt design
      behaved IDENTICALLY on `hello.c`, because Carolyne's own fetch was losing
      the instructions for a different reason (`mode="any"` on a multi-arb
      zync, CLAUDE.md §4). This gap was real and is fixed; it was not what
      `hello.c` was hitting.
      *Closes when:* Carolyne re-verifies a stage stalls its producer, ideally
      by dropping `tests/dbg_toy_model.py`'s `hold` workaround.

- [ ] **A mode="all" zync activates each target on its OWN ack.** Kathryn
      warns at elaboration ("All-mode grant is AND over (ack & cond); the
      target may activate when not all conditions are satisfied"), and the
      cycle log shows it: on `riscv_temp` at cycle 30 the LS stage 1 pip was
      entered a second time with its OLD record (`SW rob:6`) while the store
      buffer's push arb refused the transfer, so the body ran a phantom cycle
      and re-reported a finished µop. Harmless for a store, idempotent for a
      load's writeback (same value, same physical register), and wrong the
      day a squash recycles that ROB entry or register in between.
      *Where:* `carolyne/uarch/o3/exec_unit_api.py` (`with_lsq` binds
      `[(pip_con, cond), push_meta]` under `mode="all"`), the LS body's
      `zync_with_next_stage(..., with_lsq=True)`.
      *What closes it:* a mode="all" whose targets activate on the COMBINED
      grant (a Kathryn change), or a stage-1 body gated on a valid bit the
      transfer sets.

## Debug probes

- [ ] **A probe resolves only in the module that HOLDS it, and 60 of the
      machine's 941 probe signals are declared somewhere else.** Kathryn builds
      hardware in whatever module scope is open, so an arbiter LEAF's req/ack
      wires belong to the module that ZYNCS on it, and every arb's flush/hold
      wire belongs to the one module that calls `flush()` — for the whole core
      that is the branch execution complex. A probe on the arbiter's OWNER
      therefore cannot reach them. MEASURED on the 2-lane machine: 881 of 941
      probe signals resolve, and the 60 that do not are exactly 22 leaf
      req/ack, 27 arb `reset`, one `hold`, and `Rt.rename_metas`.
      `PipStatusSimProbe` reports them as UNRESOLVED and its words answer
      UNKNOWN rather than reading 0, so the log never invents a status.
      *Where:* `carolyne/debug/sim/probe_pip_status.py`,
      `Kathryn2/py/kathryn/debug_probe.py` (the LIMIT it states).
      *Closes when:* the module that DRIVES a leaf holds the probe for it (an
      `ArbLeafProbe` on the requestor), and a squash exposes its condition
      where it is built — `ExecUnitO3.dbg_resolve` already does the second
      half, which is what the log reads to show MISPRED and the redirect pc.

## Debugger

- [ ] **Live stepping.** The tools replay a recorded trace; the page's
      "next cycle" moves through the file. A simulator that steps on demand
      would implement `kathryn.observe.trace.TraceSource` and nothing in
      `kathryn.view` would change.
      *Where:* `Kathryn2/py/kathryn/observe/trace.py` (the protocol),
      `observe/record_test.py` (the loop that would take commands).
- [ ] **A served page for large traces.** The page embeds the whole trace;
      above ~30 MB the harness says so and `render --cycles a:b` embeds a
      window. A stdlib `http.server` that hands the page cycles on demand is
      the planned alternative.
      *Where:* `Kathryn2/py/kathryn/view/page_view.py`.
- [x] **Pip state by Kathryn's internal name** — CLOSED 2026-09-14: a
      `PipStatusProbe` stores `PipCon.pip_wait_reg` (the wait4syn StateReg,
      read through `arena.get_pip_wait_reg`) and `Arb.reset` (the bound
      flush wire, per arb) as manifest nodes; no name pattern is left.
      *Where:* `carolyne/debug/sim/probe_pip_status.py`, `Kathryn2/py/kathryn/complex_hardware/pip_con.py`.
- [ ] **A multi-arb zync is not grouped.** The PipCon probe exposes every
      leaf, and each non-pip leaf is one zync bind; a zync binding several
      arbiters shows as one leaf on each, with nothing that says they are
      one block.
      *Where:* `carolyne/debug/sim/probe_pip_status.py` (`leaf_status`).
      *Closes when:* `zync()` records its binds the way `pip()` records its
      leaf, and a zync probe groups them.
- [x] **Kathryn2 numbers cross-module ports from an unordered map** — CLOSED
      2026-09-11: `src/backends/common/internal_routing.rs` walks the
      dependency set in ascending global id; two emits of the 23-module
      machine are byte-identical. The build cache keeps its normalisation as
      a guard.
- [ ] **The fetch-handoff check fires in the first granted cycle after every
      squash.** `python -m examples.o3_riscv32.sim check generated/debug/hello`
      reports 18 problems, all of one shape and all two cycles after a
      mispredict (24, 35, 1054, ...): fetch's rows still show the group from
      before the flush (`0xa0/0xa4`) while decode holds the redirected group
      (`0x98/0x9c`) next cycle. Either the fetch table lags the memory port by
      the re-arm cycle, or the rule should read the port, not the table.
      *Where:* `carolyne/debugger/o3/consistency.py` (`check_fetch_handoff`),
      `uarch/o3/fetch.py`.
      *Closes when:* the rule and the hardware agree on what decode takes in
      that cycle.
- [ ] **The ISS diff.** Commit events carry pc, ROB entry, destination
      register and value for exactly that consumer; the reference model
      (`iss.py`) is not written.
      *Where:* `carolyne/debugger/o3/event_rules.py` (`commit_events`).
- [ ] **The page was run under node with a headless DOM, not opened in a
      browser by the tool.** `tests/test_view_o3_page_js.py` and Kathryn2's
      `test_view_viewer_js.py` prove the data path; the look is checked by
      opening `trace.html`.
