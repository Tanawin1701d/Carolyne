# Prf — one physical register file for ONE architectural register class
# (uop_contract.md §4.1 / Q1: per-class PRF, per-class RAT). It owns the entry
# storage plus the two numbers rename allocates from: how many entries are free,
# and which entry goes out next.
#
# `phy_amount` must be a POWER OF TWO, checked at construction: the allocation
# pointer is circular, so every step over it is arithmetic mod phy_amount, which at
# a power-of-two size is what an idx_width adder already does. The explicit wrap
# then drops out of every path — most importantly out of the mispredict
# distance, which becomes one subtraction.
#
# TWO widths, not one. `idx_width` addresses an entry (0..phy_amount-1);
# `cnt_width` holds a COUNT of free entries (0..phy_amount INCLUSIVE), one value
# more and so one bit wider — free_entry resets to phy_amount, which idx_width bits
# cannot hold.
#
# Hardware is declared in an `@init` method, never in `__init__`:
# Module.__init__ opens the module scope, runs the @init methods and closes it
# before returning, so anything declared after `super().__init__()` lands
# outside the scope — a panic standalone, or silently attached to the PARENT.
# `__init__` therefore does plain-Python configuration only, which is what lets
# it validate phy_amount before any hardware exists.
#
# Rename and commit resolve into ONE clocked write per quantity, built by the
# Prf's OWN `@flow` (`update_meta`) — automatic, once, and in the Prf's own
# UNGATED scope. That last part is load-bearing: on_rename/on_commit run
# inside their stages' zync blocks, where every assignment is gated on that
# stage's grant, so a meta write built THERE would fire only on that one
# event's cycles. Instead the always-on write reads the PORT WIRES, which are
# driven inside the granted scopes and read 0 otherwise — the gating rides in
# the wires, and the resolve composes whatever fired. The cost is that the
# PORT COUNT is a construction parameter.
#
# A mispredict is EXCLUSIVE of rename/commit, so it does not join the chain: it
# writes at raised priority and overrides them.
#
# Kathryn sizes a binary expression to its LEFT operand (expression.rs), so
# every expression here leads with the wide operand and extends the narrow one.
# Backwards, it silently truncates.

from kathryn import *

from carolyne.isa import RegFile
from carolyne.util import is_power_of_two
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
                 phy_amount   : int,
                 rename_ports : int,
                 commit_ports : int):
        # Plain-Python configuration only — see the header on @init.
        if phy_amount < 2 or not is_power_of_two(phy_amount):
            raise ValueError(
                f"Prf '{isa_reg_file.name}': phy_amount must be a power of two "
                f"(the allocation pointer wraps mod phy_amount), got {phy_amount}")
        for name, count in (("rename_ports", rename_ports),
                            ("commit_ports", commit_ports)):
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise ValueError(
                    f"Prf '{isa_reg_file.name}': {name} must be >= 1, got {count!r}")
        if rename_ports > phy_amount:
            raise ValueError(
                f"Prf '{isa_reg_file.name}': {rename_ports} rename ports on "
                f"{phy_amount} entries — the lanes of one cycle take "
                f"consecutive entries, so more ports than entries could wrap "
                f"two of them onto one")
        self.isa_reg_file = isa_reg_file
        self.phy_amount   = phy_amount
        self.rename_ports = rename_ports
        self.commit_ports = commit_ports
        # Bits addressing one of the phy_amount entries: ceil(log2(phy_amount)). Same
        # store-the-count / derive-the-log2 bargain RegFile makes with
        # amount -> index_width, so the file's size and its index can never
        # disagree.
        self.idx_width    = (phy_amount - 1).bit_length()
        # Bits holding a COUNT of free entries, 0..phy_amount inclusive — one more
        # value than there are entries, so one more bit than idx_width.
        self.cnt_width    = phy_amount.bit_length()
        super().__init__()

    @init
    def com_declare(self):
        # main datastructure
        self.storage = PrfEntry(
            HwComponentType.REG,
            (self.phy_amount,), "prf" + self.isa_reg_file.name,
            data=self.isa_reg_file.width)

        # free counter — every entry starts free
        self.free_entry = reg(self.cnt_width, "free_entry")
        self.free_entry.reset(self.phy_amount)
        # next entry to allocate; wraps mod phy_amount because phy_amount is 2**k
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
        # rename and commit arbiter
        self.rename_commit_trigger = wire(1, "rename_or_commit_trigger")

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

    def on_rename(self, dyn_idx):
        """Mark the allocated entry not-yet-written (call in the granted scope)."""
        self.storage[dyn_idx].fin |= 0
        self.rename_commit_trigger *= 1

    # ---- commit -----------------------------------------------------------------
    def on_commit(self, port, valid):
        """Return lane `port`'s entry to the pool; `valid` is a 1-bit enable."""
        self.commit_port[port] *= valid
        self.rename_commit_trigger *= 1

    # ---- resolve the cycle -------------------------------------------------------
    @flow
    def update_meta(self):
        """The cycle's one clocked write per quantity — the Prf's own flow.

        - automatic and UNGATED: built once at gen_flow, in this module's
          scope, never inside a caller's zync (whose grant would gate it)
        - the gating rides in the PORT WIRES: driven in the granted scopes,
          reading 0 otherwise, so the resolve composes whatever fired
        """
        free, next_index, over_terms = self._resolve()
        self.over_use *= any_of(over_terms)

        with zif(self.rename_commit_trigger):
            self.free_entry |= free
            self.next_index |= next_index


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
        # phy_amount is 2**k, so this adder wraps to 0 past the last entry by itself.
        pre_next_index = last_phy_idx + 1
        # Circular distance from there to the current head = the entries the
        # squashed instructions took, all of which go back to the free pool. The
        # subtraction leads with next_index, so it is mod 2**idx_width.
        reclaimed = self.next_index - pre_next_index

        # Exclusive of the rename/commit write, so priority rather than a stage.
        with priority(PRI_MIS_PRED):
            self.next_index |= pre_next_index
            self.free_entry |= self.free_entry + reclaimed.extend(self.cnt_width)
