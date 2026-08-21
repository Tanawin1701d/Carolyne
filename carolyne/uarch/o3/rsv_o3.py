# RsvO3 — out-of-order issue: of every entry whose sources have landed, the
# OLDEST one goes.
#
# MANY WRITERS, ONE ISSUE. Every front-end lane may dispatch in the same cycle
# and any of them may be aimed here, so there is one write port per lane. Each
# port finds its entry with its own reduce over the table — the free bit folded
# with its index — and the ports chain: port k's leaves drop the entries the
# earlier lanes are actually taking. A lane says which station it is for in its
# `rsv_id` field, so a station takes only the lanes that name it. Issue stays
# single: one entry leaves per cycle, for one execution unit.
#
# AGE IS THIS STATION'S OWN BUSINESS, not the register file's: it keeps a
# `track_ptr` counter and stamps every entry dispatched in one cycle with the
# same value — the track counts dispatch CYCLES, so lanes of one cycle are
# equally old and the fold breaks the tie structurally. The counter wraps, so
# `is_lower_track` is the epoch bit: set means a wrap behind, and therefore
# older; within one epoch the smaller stamp is older. On the wrap every entry
# already in the table is stamped older (`roll_track_epoch`) at a rung BELOW
# the dispatch write, so entries arriving that same cycle keep the new epoch.
#
# The order is a HEURISTIC, not a correctness property: an entry that waits
# through more than one wrap compares as merely old rather than oldest. What
# issues is always ready; only which ready one goes first can be imperfect.
#
# The winner is chosen by a Karray REDUCE read: one fold over the table carries
# the whole record, so the comparison tree is built once and the winning row
# lands on `issue_row` — the wire slot the issue block reads. Its `zync` on the
# execution unit's arbiter is what makes a busy unit stall the station instead
# of dropping the entry.

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.common import ceil_log2
from carolyne.uarch.common.karray_util import OH
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.priority import PRI_RENAME, PRI_TRACK_ROLL
from carolyne.uarch.o3.rsv import RsvBase
from carolyne.uarch.o3.rsv_helper import rsv_entry_shape


class RsvO3(RsvBase):
    """A station that issues the oldest ready entry."""

    def __init__(self,
                 config      : CPUO3_Config,
                 rsv_spec    : RsvSpec,
                 name        : str = "",
                 rsv_idx     : int = 0,
                 write_ports : int = 0):

        if not rsv_spec.issue_o3:
            raise ValueError(
                f"RsvO3 '{rsv_spec.label}': this spec asks for in-order issue, and "
                f"an in-order entry carries no age track — build an RsvIOR")

        super().__init__(config, rsv_spec, name, rsv_idx, write_ports)

    @init
    def o3_declare(self):

        self.size        = self.rsv_spec.size
        self.track_width = ceil_log2(self.size)

        # The age stamp the next dispatch cycle takes.
        self.track_ptr = reg(self.track_width, f"{self.label}_track_ptr")
        self.track_ptr.reset(0)

        # The winning entry: its whole record on a wire row (what the issue
        # block reads and hands to the FU), plus which row it came from and
        # whether it was ready at all.
        entry_cls, fields = rsv_entry_shape(self.config, self.rsv_spec)
        self.issue_row   = entry_cls(HwComponentType.WIRE, (1,),
                                     f"{self.label}_issue_row", **fields)
        self.issue_oh    = wire(self.size, f"{self.label}_issue_oh")
        self.issue_ready = wire(1, f"{self.label}_issue_ready")

        # Where each write port dispatches. Built on the first free_slots call.
        self.free_idx = [wire(self.track_width, f"{self.label}_free_idx{port}")
                         for port in range(self.write_ports)]
        self.free_ok  = [wire(1, f"{self.label}_free_ok{port}")
                         for port in range(self.write_ports)]
        self._free_built = False

    # --- dispatch ---------------------------------------------------------------
    def free_slots(self, dispatch):
        """Where each write port dispatches: one FREE entry per port, and never
        the same one twice.

        Port k is lane k — fixed, not assigned — and a lane may be carrying a
        µop for another station this cycle, so a port only has to avoid the
        entries the earlier lanes are ACTUALLY taking here. That is what
        `claimed` carries: (accepted, index) per earlier port.
        """
        if self._free_built:
            return list(zip(self.free_ok, self.free_idx))

        wants   = self.lanes_for_me(dispatch)
        claimed = []
        for port in range(self.write_ports):
            found, idx = self._find_free(claimed)
            self.free_ok[port]  *= found
            self.free_idx[port] *= idx
            # This lane takes it only if it is dispatching here at all.
            claimed.append((self.free_ok[port] & wants[port], self.free_idx[port]))

        self._free_built = True
        return list(zip(self.free_ok, self.free_idx))

    def _find_free(self, claimed):
        """(a free entry exists, which one) — the free bit reduced with its
        index, as a tree.

        What goes IN at the leaves is `~valid & not claimed by an earlier
        lane`; what comes out is the index of a row where that holds. The fold
        carries the answer in the `track` slot, which is exactly index-wide by
        construction — an extra that REPLACES a field is the only kind a caller
        can read back, since an appended one has no position in the record.
        `valid` carries "something free under me" up the same tree, so a node
        tests its subtrees' answers instead of rebuilding them.
        """
        free = self._free_bits(claimed)

        def select(lhs, rhs, level):
            lhs_free, lhs_idx = self._free_view(lhs, free)
            rhs_free, rhs_idx = self._free_view(rhs, free)
            # Prefer the left subtree, so a tie takes the lower row.
            return lhs_free, {"valid": lhs_free | rhs_free,
                              "track": mux(lhs_free, lhs_idx, rhs_idx,
                                           width=self.track_width)}

        return any_of(free), to_ref(self.table[select].track)

    def _free_bits(self, claimed):
        """Per row: free, and not one an earlier lane is taking this cycle.

        A lane bound for another station excludes nothing — it is taking no
        entry here — which is why the guard is the lane's ACCEPT and not merely
        where it was looking.
        """
        bits = []
        for row_idx in self.row_idxs():
            is_free = ~to_ref(self.table[row_idx].valid)
            for accepted, idx in claimed:
                is_free = is_free & ~(accepted & (idx == row_idx))
            bits.append(is_free)
        return bits

    def _free_view(self, view, free):
        """A subtree's answer: is anything free under it, and at which index.

        A leaf covers ONE row, so its answer is that row's free bit and its own
        index — the values the fold is seeded with. Anything wider has been
        folded already and reads its answer back out of the two slots.
        """
        if len(view.indices) == 1:
            row_idx = view.indices[0]
            return free[row_idx], val(self.track_width, row_idx)
        return view.fields["valid"], view.fields["track"]

    def write_entries(self, dispatch):
        """Take every dispatch lane aimed at this station, all in one cycle."""
        wants    = self.lanes_for_me(dispatch)
        accepted = []
        for port, (free_ok, free_idx) in enumerate(self.free_slots(dispatch)):
            accept = free_ok & wants[port]
            accepted.append(accept)
            with zif(accept):
                self.write_entry(to_ref(free_idx), dispatch[port])

        # One stamp per dispatch CYCLE, so every lane taken above is the same
        # age. Spending it can wrap the counter, which ages everything already
        # in the table.
        any_taken = any_of(accepted)
        with zif(any_taken):
            with zif(to_ref(self.track_ptr) == (1 << self.track_width) - 1):
                self.roll_track_epoch()
            self.track_ptr |= to_ref(self.track_ptr) + 1

    def write_entry(self, idx, src_row):
        """Fill one entry and stamp it with the current age.

        The stamp is SUBSTITUTED into the row copy, not written on top of it:
        the dispatch row carries a track field of its own, and two writes of
        equal priority would not order the way they read.
        """
        with priority(PRI_RENAME):
            self.table[idx] |= self.row_fields(src_row,
                                               track=to_ref(self.track_ptr),
                                               is_lower_track=0)

    def roll_track_epoch(self):
        """Every entry in the table is now a wrap behind the counter.

        Below the dispatch rung on purpose: entries written this cycle take the
        NEW epoch, and their write has to land after this one.
        """
        with priority(PRI_TRACK_ROLL):
            for row_idx in self.row_idxs():
                self.table[row_idx] |= {"is_lower_track": 1}

    # --- issue ------------------------------------------------------------------
    def build_issue(self, exec_meta, suc_tag=None):
        """The oldest ready entry issues, when the execution unit will take it.

        ONE reduce read does the choosing: the fold carries the whole record,
        so the comparison tree is built once and the winner's row lands on
        `issue_row`. `zync` then contends for the unit — a busy unit leaves the
        entry in the table instead of losing it, which is the difference from
        writing the issue as a plain `zif`.
        """
        self._root = None
        self.issue_row[0] *= self.table[self._select_oldest]
        self.issue_oh     *= self._root["oh"]
        self.issue_ready  *= self.slot_ready(self.issue_row[0])

        with cwhile(val(1, 1)):
            with zync((exec_meta, self.issue_ready)):
                self.on_issue(OH(self.issue_oh), self.issue_row[0], suc_tag)

    def _select_oldest(self, lhs, rhs, level):
        """One node of the reduce fold: which of two subtrees issues first.

        Ready beats not ready; between two ready ones the older stamp wins.
        `entry_ready` and the one-hot mask ride up as extras, so a node above
        compares subtree answers rather than rebuilding them.
        """
        lhs_ready, lhs_oh = self._folded(lhs)
        rhs_ready, rhs_oh = self._folded(rhs)

        older = ((lhs.fields["is_lower_track"] & ~rhs.fields["is_lower_track"])
                 | ((lhs.fields["is_lower_track"] == rhs.fields["is_lower_track"])
                    & (lhs.fields["track"] < rhs.fields["track"])))
        pick_lhs = lhs_ready & (~rhs_ready | older)

        ready = lhs_ready | rhs_ready
        oh    = mux(pick_lhs, lhs_oh, rhs_oh, width=self.size)

        # The node covering every row IS the root, whatever order the fold
        # visits its nodes in — that is what the issue wires read.
        if len(lhs.indices) + len(rhs.indices) == self.size:
            self._root = {"ready": ready, "oh": oh}

        return pick_lhs, {"entry_ready": ready, "entry_oh": oh}

    def _folded(self, view):
        """A subtree's answer: ready, and the one-hot of where it came from.

        A leaf has neither yet — it is one entry, so ready is its own sources
        and the mask is its own index.
        """
        if "entry_ready" in view.fields:
            return view.fields["entry_ready"], view.fields["entry_oh"]

        ready = view.fields["valid"]
        for atm_operand in self.wake_operands:
            ready = ready & view.fields[f"valid_{atm_operand.name}"]
        return ready, val(self.size, 1 << view.indices[0])
