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
