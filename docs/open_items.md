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

## Speculation (found by the debugger, 2026-09-11)

- [ ] **A branch that the ROB already drained still resolves, and its
      rollback rebuilds the ROB count from a pointer difference.** In the
      `hello.c` trace (`generated/debug/hello/trace.jsonl`, 325 commits) the
      third mispredict of every group fires with `rob.used_entry_cnt = 0`
      before the flush — a branch squashed earlier that was still in flight
      (the Mpft under-kill LIMIT in `uarch/o3/core.py`). Its `on_mis_pred`
      moves `alloc_ptr` behind or onto `com_ptr`, and the count comes back as
      `(alloc - com) mod depth`: 30 stale entries "return" (cycles 40, 1070,
      2100, 3130 — bogus commits of `li` with non-zero values) or, at cycle
      4142, `alloc == com` reads as 32 = FULL. The head entry (`rob[5]`,
      `wb_fin = 0`) then waits for a writeback no station holds, dispatch
      waits for a slot that never opens, and the machine is dead from 4143 to
      the watchdog at 6141.
      *Where:* `uarch/o3/rob.py` (`on_mis_pred`, the count after a rollback),
      `uarch/o3/core.py` (`on_mis_pred`, the Mpft booking LIMIT),
      `uarch/o3/exec_unit.py` (the per-stage kill).
      *Status:* a HARDWARE gap. The stepper shows it:
      `python -m kathryn.view.stepper generated/debug/hello/trace.jsonl`,
      then `g 4141`, `n`, `diff`, `show rob`.
      *Closes when:* a resolve or mispredict whose `rob_des_idx` is outside
      the live window `[com_ptr, alloc_ptr)` is ignored (or the Mpft booking
      kills it first), AND the count after a rollback distinguishes empty
      from full — kept incrementally (dispatched minus committed) or reloaded
      only for a branch inside the window.
- [ ] **`jal ra,98` at `0x88` redirects to `0xa8`, twice its offset.** The
      link value is right (`ra = 0x8c`); the redirect skips main's prologue
      (`lui a5 / li a4,104 / mv a5,a5 / lui a3`), so the first `putchar`
      stores 0 instead of `'h'` and the program prints `"\x00" "0" "\n"
      "\n"` where it should print `hello from carolyne\n0\n1\n4\n9\n16\n`.
      `0xa8 - 0x88 = 0x20 = 2 x 0x10`, so the J-immediate reaches the target
      adder shifted once too many — `isa/riscv/imm.py` (the placement of
      `imm_j`, checked on ints by `tests/test_imm.py`), or the target sum in
      `isa/riscv/exec_unit_br.py`, whichever adds the shift.
      *Where:* `isa/riscv/exec_unit_br.py`, `isa/riscv/imm.py`.
      *Status:* a HARDWARE gap; the trace is the evidence
      (`find commit pc=0x88`, then `n`).
      *Closes when:* the commit after `0x88` is `0x98`.

---

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

## Kathryn handshake (found by the debug probes, 2026-09-14)

- [ ] **A parked zync does not back-pressure the stage upstream of it.**
      A pip's entrance expression is `zync_state | wait4syn | start`: it
      re-arms off its own zync's STATE REGISTER (the parked request holder),
      not off the zync's grant. So while a stage's zync waits, the stage is
      re-entered every cycle, its arbiter keeps granting the stage before it,
      and that stage's writes land on top of unconsumed data. Seen on the
      toy (`tests/dbg_toy_model.py` with con_b NOT held): `a` counted through
      B's stall and `b` skipped values (7, then 12). Every O3 stage pip is
      the same top-level shape (`fetch` → `decode` → `dispatch` zync on
      `ready_to_go`). A `hold` on the arbiter does stop the entrance, which
      is how the toy stalls today.
      *Where:* `Kathryn2/src/model/flow_block/common/pip_schematic.rs`
      (`add_depend_node_to_ncp(pseudo_i, sub_wrap.get_exit_node_i(), None)`),
      the zync's exit node in `zync_schematic.rs`.
      *Closes when:* the pseudo re-arms on the zync's grant (`state & grant`),
      or the design says a stage must gate itself with `hold` — decided by
      Tanawin, then pinned by a Kathryn2 tc with a cond-gated zync.

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
