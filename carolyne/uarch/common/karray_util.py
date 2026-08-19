# Spellings for Kathryn Karray operations that have no direct statement.
#
# Nothing here is about a pipeline, a register class or an ISA — each entry
# exists because of a rule in Kathryn's Karray, and says an intent that rule
# has no single statement for.
#
# NOT re-exported from `carolyne.uarch.common`: that package's __init__ stays
# Kathryn-free, so import this module by path —
# `from carolyne.uarch.common.karray_util import OH`.

from kathryn import any_of


def OH(one_hot_sig):
    """Index a Karray dimension with a ONE-HOT signal.

    Kathryn's callable index splits by DIRECTION. On a write destination it is
    called once per index and returns that element's 1-bit enable; on a read
    source the dimension folds through a reduce tree and the callable is a 2:1
    select, picking the side whose covered indices hold the hot bit. It
    dispatches on how many arguments Kathryn hands it, so one `arr[OH(tag)]`
    serves both directions.
    """
    def index(*args):
        if len(args) == 1:                          # write: fn(i) -> enable bit
            return one_hot_sig[args[0]]
        left, _right, _level = args                 # read : fn(a, b, level) -> pick-left
        return any_of([one_hot_sig[i] for i in left.indices])
    return index
