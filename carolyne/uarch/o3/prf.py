# Prf — one physical register file for ONE architectural register class
# (uop_contract.md §4.1 / Q1: per-class PRF, per-class RAT). It owns the entry
# storage plus the two numbers rename allocates from: how many entries are free,
# and which entry goes out next.
#
# Decisions (2026-08-17):
# - `amt_num` must be a POWER OF TWO, checked at construction. The allocation
#   pointer is circular, so every step over it is arithmetic mod amt_num; at a
#   power-of-two size that is exactly what an idx_width adder already does, and
#   the explicit "== amt_num-1 ? 0 : +1" wrap drops out of every path — most
#   importantly out of the mispredict distance, which becomes one subtraction.
#   At a non-power-of-two size each of those sites needs its own compare and
#   select, for a file whose only cost of rounding up is unused entries.
# - TWO widths, not one. `idx_width` addresses an entry (0..amt_num-1);
#   `cnt_width` holds a COUNT of free entries (0..amt_num INCLUSIVE), which is
#   one value more and so one bit wider — free_entry resets to amt_num, which
#   idx_width bits cannot hold. One shared width let an index carry values past
#   the end of the file.
# - Hardware is declared in an `@init` method, never in `__init__`.
#   Module.__init__ opens the module scope, runs the @init methods, and closes it
#   before it returns, so anything declared after `super().__init__()` is outside
#   the scope: it panics ("module trace stack is empty") standalone, or silently
#   attaches to whatever module is open — the PARENT's. `__init__` therefore does
#   plain-Python configuration only, which is also what lets it validate amt_num
#   before any hardware exists.
# - Rename and commit share ONE elaboration-time chain per quantity, in the
#   spirit of Kathryn's counter.add/update: each caller appends a stage and
#   `on_update_meta` commits the head as a SINGLE clocked write. That is what
#   makes "commit + rename" in one cycle real — two independent whole-value
#   writes to free_entry would silently lose one of them. The chains restart at
#   update, so a second cycle's calls build on the register, not on the tail of
#   the first.
# - A mispredict is EXCLUSIVE of rename/commit, so it does not join the chain: it
#   writes at raised priority and overrides them.
# - Kathryn sizes a binary expression to its LEFT operand (expression.rs), so
#   every expression here leads with the wide operand and extends the narrow one.
#   Backwards, it silently truncates.

from kathryn import *
from carolyne.isa import RegFile

# Above DEFAULT_UE_PRI_USER (10), below DEFAULT_UE_PRI_INTERNAL_MIN (50), so a
# mispredict write overrides the rename/commit write of the same cycle.
PRI_MIS_PRED = DEFAULT_UE_PRI_USER + 1


class PrfEntry(Karray):
    fin  = kaf(1)       # the physical register has been written back
    data = kaf()        # no default: the instantiation sizes it from the class


class Prf(Module):


    # mispredict | commit + rename
    # the above expression mean commit and rename can exist together (+)
    # but mispredict cannot exist with the commit and rename

    def __init__(self, isa_reg_file: RegFile, amt_num: int):
        # Plain-Python configuration only — see the header on @init.
        if amt_num < 2 or (amt_num & (amt_num - 1)):
            raise ValueError(
                f"Prf '{isa_reg_file.name}': amt_num must be a power of two "
                f"(the allocation pointer wraps mod amt_num), got {amt_num}")
        self.isa_reg_file = isa_reg_file
        self.amt_num      = amt_num
        # Bits addressing one of the amt_num entries: ceil(log2(amt_num)). Same
        # store-the-count / derive-the-log2 bargain RegFile makes with
        # amount -> index_width, so the file's size and its index can never
        # disagree.
        self.idx_width    = (amt_num - 1).bit_length()
        # Bits holding a COUNT of free entries, 0..amt_num inclusive — one more
        # value than there are entries, so one more bit than idx_width.
        self.cnt_width    = amt_num.bit_length()
        super().__init__()

    @init
    def com_declare(self):
        # main datastructure
        self.storage = PrfEntry(
            HwComponentType.REG,
            (self.amt_num,), "prf" + self.isa_reg_file.name,
            data=self.isa_reg_file.width)

        # free counter — every entry starts free
        self.free_entry = reg(self.cnt_width, "free_entry")
        self.free_entry.reset(self.amt_num)
        # next entry to allocate; wraps mod amt_num because amt_num is 2**k
        self.next_index = reg(self.idx_width, "next_index")
        self.next_index.reset(0)
        # over used — a rename was booked with nothing left to give it
        self.over_use = wire(1, "overused")

        self._restart_chains()

    # ---- elaboration-time chains ----------------------------------------------
    def _restart_chains(self):
        # One stage per caller within a cycle; the head is what gets committed.
        self.free_chain = [self.free_entry]
        self.next_chain = [self.next_index]
        self.over_terms = []

    # ---- rename ----------------------------------------------------------------
    def book_rename(self, req):
        """Book one allocation; `req` is a 1-bit enable."""
        last_free = self.free_chain[-1]
        last_next = self.next_chain[-1]
        # req is 1 bit, so extending it to the accumulator's width makes the step
        # conditional with no select: move by 1 when set, by 0 when clear.
        self.free_chain.append(last_free - req.extend(self.cnt_width))
        self.next_chain.append(last_next + req.extend(self.idx_width))
        # Over-use is the borrow out of that subtraction: nothing free, yet asked.
        self.over_terms.append((last_free == 0).land(req))

    def on_rename_fill_tab(self, dyn_idx):
        self.storage[dyn_idx].fin |= 0

    # ---- commit -----------------------------------------------------------------
    # expect commit_entries as array of signal ref with width 1
    def on_commit(self, commit_entries):
        cmc = sum_cnt(commit_entries)
        # The SAME chain rename appends to, so the cycle ends in one write.
        self.free_chain.append(self.free_chain[-1] + cmc.extend(self.cnt_width))

    # ---- close the cycle --------------------------------------------------------
    def on_update_meta(self):
        self.free_entry |= self.free_chain[-1]
        self.next_index |= self.next_chain[-1]
        self.over_use   *= self._any_over_use()
        self._restart_chains()

    def _any_over_use(self):
        # Any booked rename that underflowed. No rename ports this cycle -> 0.
        if not self.over_terms:
            return 0
        reduced = self.over_terms[0]
        for term in self.over_terms[1:]:
            reduced = reduced.lor(term)
        return reduced

    # ---- read / write back -------------------------------------------------------
    def on_get_entry(self, dyn_idx):
        return self.storage[dyn_idx]

    def on_wb(self, dyn_idx, data):
        self.storage[dyn_idx].fin  |= 1
        self.storage[dyn_idx].data |= data

    # ---- mispredict ---------------------------------------------------------------
    def on_mis_pred(self, last_phy_idx):
        """Roll allocation back to just past `last_phy_idx` (idx_width bits)."""
        # amt_num is 2**k, so this adder wraps to 0 past the last entry by itself.
        pre_next_index = last_phy_idx + 1
        # Circular distance from there to the current head = the entries the
        # squashed instructions took, all of which go back to the free pool. The
        # subtraction leads with next_index, so it is mod 2**idx_width.
        reclaimed = self.next_index - pre_next_index

        # Exclusive of the rename/commit write, so priority rather than a stage.
        with priority(PRI_MIS_PRED):
            self.next_index |= pre_next_index
            self.free_entry |= self.free_entry + reclaimed.extend(self.cnt_width)
