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

- [ ] **Mpft booking is unwired.** `Mpft.on_rename` needs the current
      open-tag mask and no block owns that signal, so `get_fix_tag` reads an
      unbooked table — a squash currently computes its kill mask from rows
      nothing ever wrote.
      *Where:* `uarch/o3/mpft.py`, `uarch/o3/core.py` (`on_mis_pred`).
      *Closes when:* some block publishes the open-tag mask and dispatch calls
      `on_book_rename` / `on_rename`.

- [ ] **A destless branch rolls back no rename state.** `dest_renames` is what
      names the classes to restore, so a plain `BEQ` (which writes no register)
      restores no RT and rolls no PRF pointer back — squashed younger
      instructions' renames of that class survive.
      *Where:* `uarch/o3/core.py` (`on_mis_pred`), `uarch/o3/exec_unit.py`
      (`declare_mis_pred`, which passes `dest_renames` empty because a station
      record carries no per-dest active bit).
      *Closes when:* the record carries that bit, or a per-tag snapshot exists.
