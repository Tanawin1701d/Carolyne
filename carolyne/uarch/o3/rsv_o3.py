# RsvO3 — out-of-order issue: of every entry whose sources have landed, the
# OLDEST one goes.
#
# MANY WRITERS, ONE ISSUE. Every front-end lane may dispatch in the same cycle
# and any of them may be aimed here, so there is one write port per lane. Each
# port finds its entry with its own reduce over the table — the free bit folded
# with its index — and the ports chain: port k's leaves drop the entries the
# earlier lanes are actually taking. A lane says which station it is for in its
# `rsv_id` field, so a station takes only the lanes that name it.
#
# ONE ISSUE PATH PER EXECUTION UNIT, and they chain the same way: unit k takes
# the oldest entry IT can run that no earlier unit is taking this cycle, so two
# units issue two DIFFERENT entries in one cycle. Which entries a unit can run
# is a RANGE test on the µop id (`ExecUnitBase.uop_idx_ranges`) — one compare
# per contiguous run of ids, not one per µop — and a station with a single unit
# needs no test at all, since decode only routes it µops that unit runs.
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
# Each winner is chosen by a Karray REDUCE read: one fold per unit carries the
# whole record, so a comparison tree is built once and the winning row lands on
# that unit's `pre_issue` — the wire slot its issue block reads. The `zync` on
# the unit's own arbiter is what makes a busy unit stall its own path instead
# of dropping the entry.

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.common import ceil_log2
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.priority import PRI_RENAME, PRI_TRACK_ROLL
from carolyne.uarch.o3.operand_field import VALID, field_name
from carolyne.uarch.o3.rsv import RsvBase
from carolyne.uarch.o3.common_field import (ENTRY_IDX, ENTRY_READY,
                                            IS_LOWER_TRACK, NODE_IDX,
                                            NODE_READY, TRACK, VALID)


class RsvO3(RsvBase):
    """A station that issues the oldest ready entry."""

    def __init__(self,
                 config   : CPUO3_Config,
                 rsv_spec : RsvSpec,
                 name     : str = "",
                 rsv_idx  : int = 0):

        if not rsv_spec.issue_o3:
            raise ValueError(
                f"RsvO3 '{rsv_spec.label}': this spec asks for in-order issue, and "
                f"an in-order entry carries no age track — build an RsvIOR")

        super().__init__(config, rsv_spec, name, rsv_idx)

    @init
    def o3_declare(self):

        self.size        = self.rsv_spec.size
        self.track_width = ceil_log2(self.size)

        # The age stamp the next dispatch cycle takes.
        self.track_ptr = reg(self.track_width, f"{self.label}_track_ptr")
        self.track_ptr.reset(0)

        # Which row each unit won, as a BINARY index — the same width the
        # table's own pointers use. The record itself is on that unit's
        # `pre_issue` row and the "anything to send" bit on its
        # `issue_ready` wire, both declared by the base.
        self.issue_idx = [wire(self.track_width, f"{self.label}_issue_idx{unit_idx}")
                          for unit_idx in range(self.unit_cnt)]

        # Where each write port dispatches. Built on the first free_slots call.
        self.free_idx = [wire(self.track_width, f"{self.label}_free_idx{port}")
                         for port in range(self.config.fe_lanes)]
        self.free_ok  = [wire(1, f"{self.label}_free_ok{port}")
                         for port in range(self.config.fe_lanes)]
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
            return self.all_ok, list(zip(self.free_ok, self.free_idx))

        targets_me = self.lanes_for_me(dispatch)
        claimed    = []
        all_ok     = val(1, 1)
        for port in range(self.config.fe_lanes):
            found, idx = self._find_free(claimed)
            self.free_ok[port]  *= found
            self.free_idx[port] *= idx
            # This lane takes it only if it is dispatching here at all.
            claimed.append((self.free_ok[port] & targets_me[port],
                            self.free_idx[port]))
            # A lane bound elsewhere holds nothing against this station.
            all_ok = all_ok & (self.free_ok[port] | ~targets_me[port])
        self.all_ok *= all_ok

        self._free_built = True
        return self.all_ok, list(zip(self.free_ok, self.free_idx))

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
            return lhs_free, {VALID: lhs_free | rhs_free,
                              TRACK: mux(lhs_free, lhs_idx, rhs_idx,
                                           width=self.track_width)}

        return any_of(free), to_ref(self.table[select].track)

    def _free_bits(self, claimed):
        """Per row: free, and not one an earlier lane is taking this cycle.

        A lane bound for another station excludes nothing — it is taking no
        entry here — which is why the guard is the lane's ACCEPT and not merely
        where it was looking.
        """
        bits = []
        for row_idx in self.all_row_idxs():
            is_free = ~to_ref(self.table[row_idx].valid)
            for accepted, claim_idx_dyn in claimed:
                is_free = is_free & ~(accepted & (claim_idx_dyn == row_idx))
            bits.append(is_free)
        return bits

    def _free_view(self, view, free):
        """A subtree's answer: is anything free under it, and at which index.

        - a leaf covers ONE row, so its answer is that row's free bit and its
          own index; anything wider reads its answer out of the two slots
        """
        if len(view.indices) == 1:
            row_idx = view.indices[0]
            return free[row_idx], val(self.track_width, row_idx)
        return view.fields[VALID], view.fields[TRACK]

    def on_dispatch(self, dispatch):
        """Take every dispatch lane aimed at this station, all in one cycle."""
        targets_me     = self.lanes_for_me(dispatch)
        accepted       = []
        _all_ok, slots = self.free_slots(dispatch)
        for port, (free_ok, free_idx_dyn) in enumerate(slots):
            accept = free_ok & targets_me[port]
            accepted.append(accept)
            with zif(accept):
                self.write_entry(to_ref(free_idx_dyn), dispatch[port])

        # One stamp per dispatch CYCLE, so every lane taken above is the same
        # age. Spending it can wrap the counter, which ages everything already
        # in the table.
        any_taken = any_of(accepted)
        with zif(any_taken):
            with zif(self.track_ptr == (1 << self.track_width) - 1):
                self.roll_track_epoch()
            self.track_ptr |= self.track_ptr + 1

    def write_entry(self, row_idx_dyn, src_row):
        """Fill one entry and stamp it with the current age.

        - the stamp is SUBSTITUTED into the row copy, not written on top: two
          writes of equal priority would not order the way they read
        """
        with priority(PRI_RENAME):
            self.table[row_idx_dyn] |= self.read_row_fields(src_row,
                                                            track=self.track_ptr,
                                                            is_lower_track=0)

    def roll_track_epoch(self):
        """Every entry in the table is now a wrap behind the counter. Below the
        dispatch rung, so entries written this cycle take the NEW epoch.
        """
        with priority(PRI_TRACK_ROLL):
            for row_idx in self.all_row_idxs():
                self.table[row_idx] |= {IS_LOWER_TRACK: 1}

    # --- issue ------------------------------------------------------------------
    @flow
    def build_issue(self):
        """Each unit takes the oldest ready entry IT can run, when it will take it.

        One reduce read per unit: the fold carries the whole record, so the
        comparison tree is built once and the winner's row lands on that unit's
        `pre_issue`. The units CHAIN the way the dispatch ports do — a unit's
        leaves drop the entry an earlier unit is taking this cycle — so two
        units never issue one entry. Each `zync` contends for its OWN unit, so
        a busy unit leaves its entry in the table and holds up nothing else.
        """
        self.require_exec_meta()
        claimed = []
        for unit_idx, unit in enumerate(self.rsv_spec.exec_unit):
            issuable   = self._issuable_bits(unit, claimed)
            self._root = None                                                       # the fold fills {ready, idx}
            self.pre_issue  [unit_idx] *= self.table[self._pick_oldest(issuable)]   # one fold: tree and winner
            self.issue_lane [unit_idx] *= self.pre_issue[unit_idx]                  # on_suc_pred masks it here
            self.issue_idx  [unit_idx] *= self._root[NODE_IDX]                      # an extra, not a row field
            self.issue_ready[unit_idx] *= self._root[NODE_READY]                    # the zync condition below
            claimed.append((self.issue_ready[unit_idx], self.issue_idx[unit_idx]))  # a pick, not a grant

            with pip(self.issue_metas[unit_idx], auto_req=True, auto_restart=True):
                with zync((self.exec_metas[unit_idx], self.issue_ready[unit_idx])):
                    self.on_issue(unit_idx, to_ref(self.issue_idx[unit_idx]),
                                  self.issue_lane[unit_idx])

    def _issuable_bits(self, unit, claimed):
        """Per row: ready to go, this unit runs it, and no earlier unit is
        taking it this cycle.

        The claim is the earlier unit's SELECTION, not its grant — a unit whose
        complex is busy still holds its pick against the later ones for this
        cycle. That costs a slot, never correctness: what it holds back stays
        in the table.
        """
        bits = []
        for row_idx in self.all_row_idxs():
            row  = self.table[row_idx]
            free = self.slot_ready(row) & self.gen_uop_match_exec(unit, to_ref(row.uop_idx))
            for claim_ready, claim_idx_dyn in claimed:
                free = free & ~(claim_ready & (claim_idx_dyn == row_idx))
            bits.append(free)
        return bits

    def _pick_oldest(self, issuable):
        """The fold that reads the oldest issuable entry out of the table.

        Issuable beats not issuable; between two of them the older stamp wins.
        `entry_ready` and the winning index are carried up as extras, so a node
        compares subtree answers rather than rebuilding them.
        """
        def select(lhs, rhs, level):
            lhs_ready, lhs_idx = self._issuable_view(lhs, issuable)
            rhs_ready, rhs_idx = self._issuable_view(rhs, issuable)

            older = ((lhs.fields[IS_LOWER_TRACK] & ~rhs.fields[IS_LOWER_TRACK])
                     | ((lhs.fields[IS_LOWER_TRACK] == rhs.fields[IS_LOWER_TRACK])
                        & (lhs.fields[TRACK] < rhs.fields[TRACK])))
            pick_lhs = lhs_ready & (~rhs_ready | older)

            ready = lhs_ready | rhs_ready
            idx   = mux(pick_lhs, lhs_idx, rhs_idx, width=self.track_width)

            # The node covering every row IS the root, whatever order the fold
            # visits its nodes in — that is what the issue wires read.
            if len(lhs.indices) + len(rhs.indices) == self.size:
                self._root = {NODE_READY: ready, NODE_IDX: idx}

            return pick_lhs, {ENTRY_READY: ready, ENTRY_IDX: idx}

        return select

    def _issuable_view(self, view, issuable):
        """A subtree's answer: is anything issuable under it, and at which index.

        - a leaf covers ONE row, so its answer is that row's issuable bit and
          its own index; anything wider reads its answer out of the two slots
        """
        if ENTRY_READY in view.fields:
            return view.fields[ENTRY_READY], view.fields[ENTRY_IDX]
        row_idx = view.indices[0]
        return issuable[row_idx], val(self.track_width, row_idx)

    # --- which µops a unit may take ---------------------------------------------
    def gen_uop_match_exec(self, unit, uop_idx_dyn):
        """Build the condition that the µop this id names matches this exec
        unit: one test per contiguous RANGE of the ids it declares, not one
        per µop.

        - a unit covering the whole station tests nothing: the answer is
          always yes. That covers the single-unit station and the station
          holding two copies of one unit (two ALUs), so neither pays for a
          test it cannot fail
        """
        if self._unit_covers_station_uops(unit):
            return val(1, 1)
        hits = []
        for lo, hi in unit.uop_idx_ranges():
            hit = self._uop_idx_in_range(uop_idx_dyn, lo, hi)
            if hit is None:
                return val(1, 1)             # this range is every id there is
            hits.append(hit)
        return any_of(hits)

    def _unit_covers_station_uops(self, unit) -> bool:
        """This unit's µop ids cover every id the station can be routed — decode
        routes a station what ANY of its units runs, so that is the whole set."""
        return ({uop.uop_idx for uop in unit.uops}
                >= {uop.uop_idx for uop in self.rsv_spec.uops})

    def _uop_idx_in_range(self, uop_idx_dyn, lo: int, hi: int):
        """The id is inside one range of this unit's ids — None when the range
        holds every id the field can, and there is nothing to test.

        - a bound at the edge of the field is dropped: `>= 0` and `<= max` are
          true of every value an unsigned field holds
        """
        if lo == hi:
            return uop_idx_dyn == lo
        bounds = []
        if lo > 0:
            bounds.append(uop_idx_dyn >= lo)
        if hi < (1 << self.config.uop_idx_width) - 1:
            bounds.append(uop_idx_dyn <= hi)
        if not bounds:
            return None
        return bounds[0] if len(bounds) == 1 else bounds[0] & bounds[1]
