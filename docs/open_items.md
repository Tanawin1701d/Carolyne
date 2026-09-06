# Open items

Every known gap in one place: what is missing, where it lives, and what would
close it. A `LIMIT:` marker in the source is the same fact stated at the point
a reader meets it — this file is the index, the code is the record.

Scope: things that are DELIBERATELY unfinished. A bug goes in the tracker, not
here; a decision already made and recorded goes in CLAUDE.md §4, not here.

---

## Load / store

- [ ] **Misaligned `LW` / `LH` return the containing word.** The low two
      address bits are discarded, so `LW` at `0x2` returns the word at `0x0`
      and `LH` at an odd address reads the wrong two bytes. Stores have the
      same gap. RV32I permits an implementation to SUPPORT misaligned accesses
      or to RAISE an address-misaligned exception — silently-wrong data is
      neither.
      *Where:* `isa/riscv/exec_unit_ls.py` (`_address_stage`).
      *Closes when:* either a misalignment detect that traps (blocked on trap
      policy), or a two-word read + concatenate for spanning accesses.

## Speculation

- [ ] **A squash under-kills: the Mpft is seeded with one tag, not the mask.**
      Booking is wired — dispatch's `warm_mpft` registers every lane and
      `update_mpft` calls `on_rename` — but it passes `TagGen.get_last_tag()`,
      the NEWEST open tag, where `on_rename` wants the mask of EVERY open tag.
      A row then lists the tag before it instead of all the tags it is under,
      and `get_fix_tag` reads one column with no transitive closure, so
      younger speculations survive: with tags A, B, C open and D booked,
      squashing A kills B and leaves C and D alive.
      *Where:* `uarch/o3/dispatch.py` (`update_mpft`, which states this),
      `uarch/o3/tag_gen.py`, `uarch/o3/mpft.py` (`on_rename`).
      *Closes when:* a block publishes the OPEN-TAG MASK. `TagGen` is the
      natural owner — it is the allocator and already sees booking, resolve
      and squash — as an `open_tags` register set on `book_rename` and cleared
      on `on_suc_pred` / `on_mis_pred`. Deriving it from `free_tag` +
      `next_tag` costs a barrel shifter and a fill, so the register is
      cheaper; `_spec_before`'s "is anything open" test then becomes
      `open_tags != 0`, so the new state replaces existing state rather than
      sitting beside it.
