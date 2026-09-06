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

- [ ] **A squash may still under-kill across a WRAP.** The Mpft is seeded
      correctly now: `on_rename` reads back the row of the newest open tag
      (`Mpft.open_tags`), and because row T holds every tag T sits under plus
      T itself, that row IS the open set — so no block has to publish one and
      `TagGen` needs no extra state. The chain self-heals on a resolve, since
      `on_suc_pred` clears the resolved tag from every row.
      What is NOT covered: `get_last_tag()` names the most recently handed-out
      tag, so the chain is only as good as that pointer. After the tag pointer
      wraps and a tag is rebooked, the row it chains from is the REBOOKED
      tag's, not the older speculation's.
      *Where:* `uarch/o3/mpft.py` (`open_tags`, `on_rename`),
      `uarch/o3/tag_gen.py` (`get_last_tag`).
      *Closes when:* someone works out whether the wrap is reachable at all —
      `TagGen.over_use` refuses a booking with no tag left, so the pool may
      already make it impossible, in which case this entry is a note rather
      than a gap. If it IS reachable, an explicit open-tag register on TagGen
      (set on `book_rename`, cleared on `on_suc_pred` / `on_mis_pred`) does
      not depend on a pointer at all.
