# Open items

Every known gap in one place: what is missing, where it lives, and what would
close it. A `LIMIT:` marker in the source is the same fact stated at the point
a reader meets it — this file is the index, the code is the record.

Scope: things that are DELIBERATELY unfinished. A bug goes in the tracker, not
here; a decision already made and recorded goes in CLAUDE.md §4, not here.

---

## Front end

- [ ] **decode routes nothing to a real station.** `uop_decode` writes
      `is_branch` / `is_store` / `rsv_id` as ZERO, so every valid lane names
      station 0 and reads as non-branch, non-store.
      *Where:* `uarch/o3/decode.py` (`uop_decode`, the `TODO:` at ~line 185).
      *Closes when:* the description layer can say which µop templates are
      branches / stores, and which station each kind routes to. Until then the
      LS and branch paths are structurally complete but **idle at runtime** —
      no µop ever reaches the mem station.

- [ ] **The immediate-extraction rule is a placeholder.**
      `extract_imm_value` reads the first segment lowest, with no sign
      extension and no placement, so `imm_b` / `imm_j` are wrong.
      *Where:* `uarch/common/word_util.py`.
      *Closes when:* a matcher can say where each segment lands in the
      assembled value — the open half of the encoding contract (§1.3).

- [ ] **An inactive source slot blocks issue.** decode writes `valid_<n>`=0 for
      a slot the µop does not fill, and `RsvBase.slot_ready` ANDs EVERY wake
      operand's valid bit.
      *Where:* `uarch/o3/decode.py`, `uarch/o3/rsv.py` (`slot_ready`).
      *Closes when:* decode writes those slots' valid as 1, or `slot_ready`
      gates on `active`.

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

- [ ] **A store pushed in the cycle its tag resolves keeps the stale tag.**
      Same family as the stage-hop race below; `RsvBase.on_issue` solves its
      version by substituting into the copy.
      *Where:* `uarch/o3/exec_unit.py` (`lsq_push_store`).

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

- [ ] **A record hopping stages in the resolve cycle copies its tag before the
      mask lands.**
      *Where:* `uarch/o3/exec_unit_api.py` (`zync_with_next_stage`).
      *Closes when:* the transfer learns the same substitution `on_issue` uses.

## Back end

- [ ] **Nothing calls `build_issue`.** The stations' issue blocks are built,
      and each complex's `exec_meta` is the arb they would zync against, but
      no caller connects the two — so no entry ever issues into an execution
      unit.
      *Where:* `uarch/o3/core.py`, `uarch/o3/rsv_o3.py` / `rsv_ior.py`.

## To revise

Not gaps — these are built and elaborate. Tanawin wants the DESIGN
re-examined before it hardens; the notes under each are what a reader might
start from, not a verdict.

- [ ] **The bypass system.** A writeback broadcasts one `RsvBypass` per
      register class to EVERY station, and each station walks every row ×
      every wake operand comparing `pr_idx`.
      *Where:* `uarch/o3/rsv.py` (`RsvBypass`, `on_bypass`),
      `uarch/o3/exec_unit.py` (`wb_reg`).
      *Worth looking at:* the comparator count grows as
      stations × rows × wake-operands; whether a µop issuing in the SAME
      cycle as the broadcast sees it; and that the PRF write and the
      broadcast are two paths carrying one value.

- [ ] **The successful-prediction system.** `on_suc_pred` stalls dispatch for
      the cycle, masks the tag out of every station and every stage record,
      hands the tag back to `TagGen` and clears it from the Mpft.
      *Where:* `uarch/o3/core.py` (`on_suc_pred`),
      `uarch/o3/exec_unit.py` (`declare_suc_pred`), `uarch/o3/tag_gen.py`.
      *Worth looking at:* the dispatch stall fires on every CORRECTLY
      predicted branch — the common case — so it costs a dispatch slot per
      resolve; `tag_gen.on_suc_pred(val(1,1))` passes a constant where the
      port is an enable; and `rob_des_idx_dyn` is accepted but unused,
      reserved for the predictor update that does not exist yet.
