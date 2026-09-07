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
