# The o3 engine's write-priority ladder — which write wins when two of them
# land on the same component in the same cycle.
#
# Kathryn emits a component's update events in ASCENDING priority inside one
# `always` block, so the LAST one emitted is the one that takes effect. A block
# that layers writes therefore names a rung per layer, and the rungs here are
# that ladder for the whole engine.
#
# Decisions (2026-08-18):
# - ONE HOME, because a rung only means something if every block reads the same
#   one. `PRI_MIS_PRED` was defined three times — in rt.py at USER+5, in prf.py
#   and tag_gen.py at USER+1 — which is three chances for the engine to disagree
#   with itself about which write wins. The values that survived are rt.py's: it
#   is the only block with more than one rung, so it is the only one that ever
#   needed a scale. The other two were only ever asking for "above the default",
#   which USER+5 satisfies exactly as well as USER+1 did, so unifying them
#   changed no hardware.
# - NAMED FOR EVENTS, not for blocks. A rung is a moment in the pipeline —
#   something commits, something renames, a prediction turns out wrong — and
#   every structure that moment touches has to order its writes the same way.
#   `Rt`, `Prf` and `TagGen` all take `PRI_MIS_PRED` to mean the same instant.
# - THE BAND is strictly between Kathryn's own constants: above
#   DEFAULT_UE_PRI_USER (10), so a rung beats every plain assignment, and below
#   DEFAULT_UE_PRI_INTERNAL_MIN (50), so nothing here collides with the fallback
#   and routing events Kathryn builds for itself. Room is left between the rungs
#   and under the ceiling for events not yet written (a trap, a full flush).
# - THE BOTTOM RUNG IS NOT HERE. Structural work — a row copied forward, a
#   register reloaded every cycle — runs at DEFAULT_UE_PRI_USER simply by not
#   naming a priority at all. Kathryn already owns that constant, and a second
#   name for it would be a second answer to the same question.
# - This lives in `o3/`, not in `uarch/common/`, on two counts: these are the
#   events of an OUT-OF-ORDER pipeline, and another engine has different ones;
#   and `common/` is deliberately Kathryn-free, while a rung cannot be stated
#   without DEFAULT_UE_PRI_USER.
#
# The rule that makes the ladder load-bearing rather than decorative: at EQUAL
# priority the emission order is NOT the order the statements were written — an
# assignment made inside a flow block (`zif`) is emitted BEFORE every
# unconditional one. So "copy the row, then overlay the exception" only builds
# what it reads like when the overlay names a higher rung; written plainly it
# produces the opposite hardware, silently.

from kathryn import DEFAULT_UE_PRI_USER

# A mapping retires: the physical register goes back to the free pool, so every
# structure still naming it has to stop.
PRI_COMMIT   = DEFAULT_UE_PRI_USER + 3

# A lane renames: it writes its destination, and a branch checkpoints the state
# it leaves behind. Above commit, because a rename supersedes a retirement of
# the same architectural register in the same cycle.
PRI_RENAME   = DEFAULT_UE_PRI_USER + 4

# A prediction turns out wrong: speculative state is rolled back. The top rung,
# because it overrides the whole cycle's work rather than joining it.
PRI_MIS_PRED = DEFAULT_UE_PRI_USER + 5
