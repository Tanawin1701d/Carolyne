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
# - Rename and commit resolve into ONE clocked write per quantity, in the spirit
#   of Kathryn's counter.add/update: the callers state what happened and
#   `on_update_meta` commits the result. That is what makes "commit + rename" in
#   one cycle real — two independent whole-value writes to free_entry would
#   silently lose one of them.
# - CALL ORDER MUST NOT MATTER — for ANY of the three, including which one runs
#   last. That is why the ports are WIRES declared in `com_declare` and the
#   methods only DRIVE them: `book_rename` and `on_commit` connect a source to a
#   port, `on_update_meta` reads the ports and emits the writes, and a wire read
#   before it is driven still connects, because these are netlist nodes and not
#   values. So the three compose in HARDWARE, where the order they were spoken in
#   cannot be observed, instead of in a Python accumulator that only reads right
#   if the calls arrived in the intended sequence.
#   Two earlier shapes were tried and are not worth restoring. Appending to a
#   chain per caller made `over_use` depend on the rename/commit order: called
#   before `on_commit`, a rename judged a pool the commit was refilling as empty
#   and raised exhaustion on an entry that was available, so a caller stalling on
#   `over_use` lost that slot every time the free list ran dry mid-refill. (The
#   COUNT was always fine — (free-req)+cmc and (free+cmc)-req agree, and the
#   intermediate underflow unwraps modulo 2**cnt_width.) Recording the terms and
#   assembling them at update fixed that, but left `on_update_meta` obliged to
#   run last: called early, it reset the record and every later `book_rename`
#   vanished from the netlist with no error at all.
# - The cost is that the PORT COUNT is now a construction parameter, since a
#   declared network cannot discover its own width from how many times a method
#   happened to be called. That is the honest shape anyway — a machine has a
#   fixed number of rename and commit ports, and they are what the widths of this
#   logic were always describing.
# - A mispredict is EXCLUSIVE of rename/commit, so it does not join the chain: it
#   writes at raised priority and overrides them.
# - Kathryn sizes a binary expression to its LEFT operand (expression.rs), so
#   every expression here leads with the wide operand and extends the narrow one.
#   Backwards, it silently truncates.

from kathryn import *

from carolyne.isa import RegFile
# One rung of the engine-wide ladder (priority.py): a mispredict write overrides
# the rename/commit write of the same cycle.
from carolyne.uarch.o3.priority import PRI_MIS_PRED


class PrfEntry(Karray):
    fin  = kaf(1)       # the physical register has been written back
    data = kaf()        # no default: the instantiation sizes it from the class


class Prf(Module):


    # mispredict | commit + rename
    # the above expression mean commit and rename can exist together (+)
    # but mispredict cannot exist with the commit and rename

    def __init__(self,
                 isa_reg_file : RegFile,
                 amt_num      : int,
                 rename_ports : int,
                 commit_ports : int):
        # Plain-Python configuration only — see the header on @init.
        if amt_num < 2 or (amt_num & (amt_num - 1)):
            raise ValueError(
                f"Prf '{isa_reg_file.name}': amt_num must be a power of two "
                f"(the allocation pointer wraps mod amt_num), got {amt_num}")
        for name, count in (("rename_ports", rename_ports),
                            ("commit_ports", commit_ports)):
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError(
                    f"Prf '{isa_reg_file.name}': {name} must be >= 1, got {count!r}")
        self.isa_reg_file = isa_reg_file
        self.amt_num      = amt_num
        self.rename_ports = rename_ports
        self.commit_ports = commit_ports
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

        # PORTS. Declared once, here, and only DRIVEN by the methods below —
        # which is what makes call order irrelevant (header). An undriven port
        # reads its default, so a lane that books nothing contributes nothing.
        self.req_port    = [wire(1, "rename_req{}".format(i)).default(0)
                            for i in range(self.rename_ports)]
        self.commit_port = [wire(1, "commit_valid{}".format(i)).default(0)
                            for i in range(self.commit_ports)]

    # ---- rename ----------------------------------------------------------------
    def book_rename(self, port, req):
        """Book lane `port`'s allocation; `req` is a 1-bit enable.

        Returns the entry that lane gets — the pointer plus however many lanes
        BEFORE it are booking, so the lanes of one cycle take consecutive
        entries. It reads the other lanes' port wires, which is legal whether or
        not they have been driven yet.
        """
        self.req_port[port] *= req
        index = self.next_index
        for earlier in self.req_port[:port]:
            index = index + earlier.extend(self.idx_width)
        return index

    def on_rename_fill_tab(self, dyn_idx):
        self.storage[dyn_idx].fin |= 0

    # ---- commit -----------------------------------------------------------------
    def on_commit(self, port, valid):
        """Return lane `port`'s entry to the pool; `valid` is a 1-bit enable."""
        self.commit_port[port] *= valid

    # ---- resolve the cycle -------------------------------------------------------
    def on_update_meta(self):
        free, next_index, over_terms = self._resolve()
        self.free_entry |= free
        self.next_index |= next_index
        self.over_use   *= any_of(over_terms)

    def _resolve(self):
        """The cycle's free count and allocation pointer, read off the PORT
        WIRES rather than off anything a caller accumulated.

        Commits lead STRUCTURALLY — their sum is wired ahead of the rename
        subtractions — so a commit retiring an instruction older than a rename
        beside it really does refill the pool that rename draws from, and no
        call order can change that. Reading wires instead of recorded terms is
        also what frees this method from having to run last.
        """
        free       = self.free_entry + sum_cnt(self.commit_port).extend(self.cnt_width)
        next_index = self.next_index

        over_terms = []
        for req in self.req_port:
            # Over-use is the borrow out of the subtraction below: nothing free,
            # yet asked — judged against a pool the commits have already refilled.
            over_terms.append((free == 0).land(req))
            free       = free - req.extend(self.cnt_width)
            next_index = next_index + req.extend(self.idx_width)
        return free, next_index, over_terms

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
