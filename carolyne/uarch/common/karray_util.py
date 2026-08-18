# Spellings for Kathryn Karray operations that have no direct statement.
#
# Nothing here is about a pipeline, a register class or an ISA — each entry
# exists because of a rule in Kathryn's Karray, and says an intent that rule
# has no single statement for.
#
# Decisions (2026-08-18):
# - Here rather than in the block that first needed it. `OH` was written in
#   rt.py and is now wanted by mpft.py, and one-hot tags are how this engine
#   addresses speculation everywhere — a second copy is a second chance to
#   disagree. What is SHARED moves; what is still local to one block stays
#   there (rt.py keeps `write_entry` and `copy_row` until something else asks).
# - `uarch/common/` rather than `uarch/o3/`, because a Karray rule is a fact
#   about Kathryn and not about out-of-order execution.
# - NOT re-exported from `carolyne.uarch.common`. That package's __init__ pulls
#   in block_manager and hw_util, both deliberately Kathryn-free so the block
#   lifecycle stays testable with no arena; re-exporting this module would put
#   a Kathryn import behind `from carolyne.uarch.common import ceil_log2`.
#   Import it by module: `from carolyne.uarch.common.karray_util import OH`.

from kathryn import any_of


def OH(one_hot_sig):
    """Index a Karray dimension with a ONE-HOT signal.

    Kathryn's callable index splits by DIRECTION. On a write destination it is
    called once per index and returns that element's 1-bit enable; on a read
    source the dimension folds through a reduce tree and the callable is a 2:1
    select, picking the side whose covered indices hold the hot bit. One object
    serves both, dispatching on how many arguments Kathryn hands it — which is
    what lets the same `arr[OH(tag)]` be written in one method and read in
    another without the caller stating which direction it meant.
    """
    def index(*args):
        if len(args) == 1:                          # write: fn(i) -> enable bit
            return one_hot_sig[args[0]]
        left, _right, _level = args                 # read : fn(a, b, level) -> pick-left
        return any_of([one_hot_sig[i] for i in left.indices])
    return index
