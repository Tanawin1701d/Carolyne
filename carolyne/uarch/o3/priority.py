# The o3 engine's write-priority ladder — which write wins when two of them
# land on the same component in the same cycle.
#
# Kathryn emits a component's update events in ASCENDING priority inside one
# `always` block, so the LAST one emitted is the one that takes effect. A block
# that layers writes therefore names a rung per layer, and the rungs here are
# that ladder for the whole engine.
#
# ONE HOME, because a rung only means something if every block reads the same
# one. Rungs are NAMED FOR EVENTS, not for blocks: a rung is a moment in the
# pipeline, and every structure that moment touches orders its writes the same
# way. The band sits strictly between Kathryn's own constants — above
# DEFAULT_UE_PRI_USER (10), so a rung beats every plain assignment, and below
# DEFAULT_UE_PRI_INTERNAL_MIN (50), so nothing collides with the fallback and
# routing events Kathryn builds for itself. Room is left between the rungs for
# events not yet written (a trap, a full flush).
#
# THE BOTTOM RUNG IS NOT HERE: structural work — a row copied forward, a
# register reloaded every cycle — runs at DEFAULT_UE_PRI_USER by not naming a
# priority at all.
#
# This lives in `o3/` rather than `uarch/common/`: these are the events of an
# OUT-OF-ORDER pipeline, and `common/` is deliberately Kathryn-free.

# The rule that makes the ladder load-bearing rather than decorative: at EQUAL
# priority the emission order is NOT the order the statements were written — an
# assignment made inside a flow block (`zif`) is emitted BEFORE every
# unconditional one. So "copy the row, then overlay the exception" only builds
# what it reads like when the overlay names a higher rung; written plainly it
# produces the opposite hardware, silently.

from kathryn import DEFAULT_UE_PRI_USER

# A station's age epoch rolls over: every entry already in the table is stamped
# older. The bottom-most rung, because it must LOSE to the entry dispatch writes
# in the same cycle — that entry belongs to the NEW epoch.
PRI_TRACK_ROLL = DEFAULT_UE_PRI_USER + 1

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
