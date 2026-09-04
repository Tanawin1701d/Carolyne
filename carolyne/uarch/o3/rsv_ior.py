# RsvIOR — in-order issue: entries leave in the order they arrived, so the
# station is a circular FIFO and position IS the age. That is why an in-order
# entry carries no age track (rsv_helper).
#
# MANY WRITERS, ONE ISSUE, the same shape RsvO3 has: one write port per
# front-end lane, and a lane says which station it is for in its `rsv_id`
# field. What differs is that this station does not SEARCH — an in-order table
# is contiguous by construction, so `alloc_ptr` already names where the next
# entry goes and `head_ptr` the one that issues next. There is no free-slot
# fold here because there is nothing to look for.
#
# The lanes land in a RUN from `alloc_ptr` that COMPACTS: a port's offset is
# how many earlier lanes are dispatching here, so a lane bound elsewhere leaves
# no gap. A lane that wants in and cannot BLOCKS every later one — in order, a
# gap would be an entry issuing before one dispatched ahead of it.
#
# A squash always takes the YOUNGEST entries, so the survivors stay a prefix
# from the head and the allocation pointer is head + however many survived.
# The C++ original searches its busy column for the same answer; two pointers
# are the same machine with the search already done.
#
# The row count must be a POWER OF TWO for that arithmetic: both pointers step
# modulo the table, and at a power-of-two size the modulo IS the width of the
# register, so no wrap comparison is built anywhere (the bargain Prf makes).

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.common import ceil_log2
from carolyne.util import is_power_of_two
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.priority import PRI_MIS_PRED, PRI_RENAME
from carolyne.uarch.o3.rsv import RsvBase


class RsvIOR(RsvBase):
    """A station that issues its head entry."""

    def __init__(self,
                 config   : CPUO3_Config,
                 rsv_spec : RsvSpec,
                 name     : str = "",
                 rsv_idx  : int = 0):

        if rsv_spec.issue_o3:
            raise ValueError(
                f"RsvIOR '{rsv_spec.label}': this spec asks for out-of-order issue "
                f"— build an RsvO3, which reads the age track this entry has not got")
        if rsv_spec.size < 2:
            raise ValueError(
                f"RsvIOR '{rsv_spec.label}': {rsv_spec.size} entry — an in-order "
                f"station addresses its table with two pointers, and one entry "
                f"leaves them 0 bits wide")
        if not is_power_of_two(rsv_spec.size):
            raise ValueError(
                f"RsvIOR '{rsv_spec.label}': {rsv_spec.size} entries — an in-order "
                f"station steps two pointers modulo its size, so the size must be a "
                f"power of two or every step needs its own wrap compare")

        # One write port per front-end lane — the check has to run BEFORE
        # super(), which is what builds the hardware.
        if config.fe_lanes > rsv_spec.size:
            raise ValueError(
                f"RsvIOR '{rsv_spec.label}': {config.fe_lanes} write ports over "
                f"{rsv_spec.size} entries — the lanes land in a RUN from one pointer, "
                f"so two of them would come back round onto the same entry and write "
                f"it twice in a cycle. Deepen the station to at least fe_lanes")

        super().__init__(config, rsv_spec, name, rsv_idx)

    @init
    def ior_declare(self):

        self.size      = self.rsv_spec.size
        self.idx_width = ceil_log2(self.size)

        # Where the next dispatch lands, and the entry that issues next. Both
        # wrap on their own width, which is the table size.
        self.alloc_ptr = reg(self.idx_width, f"{self.label}_alloc_ptr")
        self.alloc_ptr.reset(0)
        self.head_ptr  = reg(self.idx_width, f"{self.label}_head_ptr")
        self.head_ptr.reset(0)

        # The head's record on a wire row, and whether it can go — the same
        # materialised slot RsvO3 folds its winner onto.
        self.issue_ready = wire(1, f"{self.label}_issue_ready")

        # Where each write port lands. Built on the first free_slots call, like
        # RsvO3's: a second build would double-drive the same wires.
        self.free_ok  = [wire(1, f"{self.label}_free_ok{port}")
                         for port in range(self.config.fe_lanes)]
        self.free_idx = [wire(self.idx_width, f"{self.label}_free_idx{port}")
                         for port in range(self.config.fe_lanes)]
        self._free_built = False

    # --- dispatch ---------------------------------------------------------------
    def free_slots(self, dispatch):
        """A run from the allocation pointer, one entry per write port.

        In order there is no choice about WHERE a lane lands, so this computes
        the answer instead of searching for it: port k takes the pointer plus
        however many EARLIER lanes are dispatching here.

        The offset counts the lanes TARGETING this station, not the ones that
        land. Those differ only when an earlier lane was refused for want of
        room — and a refused lane blocks every later one anyway
        (`on_dispatch`), so the offset can only be wrong on a port that is
        taking nothing.

        The index is that offset MODULO the table, and two wanting lanes would
        share a row only if their offsets differed by a whole table — which the
        `fe_lanes <= size` refused at construction makes impossible, since
        the largest difference is then size - 1.
        """
        if self._free_built:
            return self.all_ok, list(zip(self.free_ok, self.free_idx))

        targets_me = self.lanes_for_me(dispatch)
        alloc      = self.alloc_ptr
        all_ok     = val(1, 1)
        for port in range(self.config.fe_lanes):
            offset = None if port == 0 else sum_cnt(targets_me[:port])
            self.free_idx[port] *= alloc if offset is None else alloc + offset
            self.free_ok[port]  *= ~to_ref(
                self.table[self.free_idx[port]].valid)
            # A lane bound elsewhere holds nothing against this station.
            all_ok = all_ok & (self.free_ok[port] | ~targets_me[port])
        self.all_ok *= all_ok

        self._free_built = True
        return self.all_ok, list(zip(self.free_ok, self.free_idx))

    def on_dispatch(self, dispatch):
        """Take the lanes aimed at this station, in order, from the pointer on.

        A lane may only land if every earlier lane bound for this station did.
        The pointer then moves on by however many were taken.
        """
        targets_me        = self.lanes_for_me(dispatch)
        accepted, blocked = [], None
        _all_ok, slots    = self.free_slots(dispatch)
        for port, (free, idx) in enumerate(slots):
            accept = targets_me[port] & free
            if blocked is not None:
                accept = accept & ~blocked
            # An earlier lane that targeted this station and could not land
            # blocks the rest.
            missed  = targets_me[port] & ~accept
            blocked = missed if blocked is None else blocked | missed

            accepted.append(accept)
            with zif(accept):
                self.write_entry(to_ref(idx), dispatch[port])

        with priority(PRI_RENAME):
            self.alloc_ptr |= self.alloc_ptr + sum_cnt(accepted)

    # --- issue ------------------------------------------------------------------
    def build_issue(self, exec_meta):
        """The head issues when its sources have landed and the unit will take
        it. Nothing younger may overtake — that is the whole difference from
        RsvO3, and it is why this needs no comparison tree, only a pointer.

        The head's record is copied onto a wire row first, so the issue block
        reads one materialised slot rather than reading the table again inside
        the arbitrated block. `zync` on the unit's arbiter is what makes a busy
        unit STALL the station: the entry stays, where a plain `zif` would have
        cleared it into a unit that never took it.
        """
        head = self.head_ptr
        self.pre_issue [0] *= self.table[head]
        self.issue_lane[0] *= self.pre_issue[0]
        self.issue_ready  *= self.slot_ready(self.pre_issue[0])

        with pip(self.issue_meta, auto_req=True, auto_restart=True):
            with zync((exec_meta, self.issue_ready)):
                self.on_issue(head, self.issue_lane[0])
                self.head_ptr |= head + 1

    # --- squash -----------------------------------------------------------------
    def on_mis_pred(self, fix_tag):
        """Kill the speculating entries, then pull the allocation pointer back.

        A squash always takes the youngest entries, so what survives is still a
        contiguous run starting at the head: the pointer belongs one past the
        last survivor, which is head + the number of them. The head itself does
        not move — the entries before the branch are still going to issue.

        Which entries die is `entry_squashed`, the same predicate the base uses
        to clear them, read back rather than restated.

        The count reads the CURRENT valid bits, so an entry issuing in this
        same cycle is still counted; that is right, because the head moves on
        by one at the same time.
        """
        super().on_mis_pred(fix_tag)

        survivors = [to_ref(self.table[row_idx].valid)
                     & ~self.entry_squashed(self.table[row_idx], fix_tag)
                     for row_idx in self.all_row_idxs()]

        with priority(PRI_MIS_PRED):
            self.alloc_ptr |= self.head_ptr + sum_cnt(survivors)
