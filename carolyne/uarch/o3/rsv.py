# RsvBase — one reservation station: the entries waiting for their sources, and
# the one entry that issued this cycle. A subclass supplies `build_issue`,
# which is where the age-ordered and in-order policies differ.
#
# The three moments this block layers writes for, highest rung first:
#
#   mispredict          PRI_MIS_PRED  kill every entry under the bad tag
#   an entry dispatched PRI_RENAME    dispatch writes it, same instant as rename
#   issue / bypass /    (bottom rung) the ordinary cycle's work
#   resolved prediction
#
# The first two cannot happen to one entry in the same cycle; the ladder is
# what makes that assumption safe if they ever do (priority.py).
#
# Everything here is written against the ISA-derived field names of
# rsv_helper: `valid_<n>` / `pr_idx_<n>` / `data_<n>` per source, so a station
# waits on exactly the operands its exec units read, whatever the ISA is.
# Only an ARCH source waits — a µtemp/immediate rides with the µop and has no
# physical register to wake on.

from dataclasses import dataclass

from kathryn import *
from kathryn.signal import to_ref

from carolyne.isa import RegFile
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.operand_field import DATA, PR_IDX, VALID, field_name
from carolyne.uarch.o3.priority import (PRI_ISSUE, PRI_MIS_PRED,
                                        PRI_RENAME, PRI_SUC_PRED)
from carolyne.uarch.o3.rsv_helper import (build_rsv_slot, build_rsv_table,
                                          rsv_entry_shape, rsv_field_names,
                                          station_atm_operands)


@dataclass(frozen=True, eq=False)
class RsvBypass:
    """One writeback broadcast: a physical register of `reg_file` now holds a
    value. Per class, because each renamed class has its own PRF and its own
    index space — a station only wakes the sources that name that class.

    NO valid bit: `on_bypass` builds its writes in the scope wb_reg was
    called from, so the caller's own zif already gates them. A bit here
    would say a second time what the enclosing scope says."""
    reg_file : RegFile
    pr_idx   : object       # which physical register was written
    data     : object       # the value it now holds


class RsvBase(Module):
    """A reservation station's storage and the events that move it.

    Build it from the @init of the module that owns the station. `build_issue`
    is left to a subclass: which ready entry goes next is the station's policy.
    """

    def __init__(self,
                 config      : CPUO3_Config,
                 rsv_spec    : RsvSpec,
                 name        : str = "",
                 rsv_idx     : int = 0):

        self.config   = config
        self.rsv_spec = rsv_spec
        self.rsv_idx  = rsv_idx         # which station a dispatch bus names
        self.label    = name or f"rsv_{rsv_spec.label.replace('/', '_')}"

        super().__init__()

    @init
    def com_declare(self):

        self.table    = build_rsv_table(self.config, self.rsv_spec, self.label)
        self.exec_src = build_rsv_slot(self.config, self.rsv_spec,
                                       f"{self.label}_exec")

        # The issue block's own arbiter: always requesting, restarted by a
        # flush, so build_issue runs as a pip instead of an eternal cwhile.
        self.issue_meta = PipCon(name=f"{self.label}_issue")

        # The entry AS IT WILL LAND: a subclass drives `pre_issue` with its
        # chosen row, this lane copies it, and a prediction resolving in the
        # SAME cycle overrides the speculation pair here — combinationally,
        # before the clocked copy into `exec_src`, so nothing has to race a
        # register that has not been written yet.
        entry_cls, fields = rsv_entry_shape(self.config, self.rsv_spec)
        self.pre_issue    = entry_cls(HwComponentType.WIRE, (1,),
                                      f"{self.label}_pre_issue", **fields)
        self.issue_lane   = entry_cls(HwComponentType.WIRE, (1,),
                                      f"{self.label}_issue_lane", **fields)

        # The atomic operands this station's entries carry, and the subset a
        # writeback can wake: an arch source is the only one with a valid_ bit
        # and a physical index.
        self.atm_operands          = station_atm_operands(self.config.isa,
                                                          self.rsv_spec)
        self.has_src_arch_operands = tuple(a for a in self.atm_operands
                                           if a.is_src and a.has_arch)
        self.entry_fields          = rsv_field_names(self.config, self.rsv_spec)
        self._lane_targets_me      = None   # built on the first lanes_for_me

        # free_slots' aggregate answer: every lane aimed here can land — the
        # station's own contribution to the dispatch go/stall bit.
        self.all_ok = wire(1, f"{self.label}_all_ok")

    # --- reads -----------------------------------------------------------------
    def slot_ready(self, row):
        """This entry is occupied and every source it waits on has landed."""
        ready = to_ref(row.valid)
        for atm_operand in self.has_src_arch_operands:
            ready = ready & to_ref(getattr(row, field_name(VALID, atm_operand)))
        return ready

    def all_row_idxs(self):
        """Every row index of the table. A Karray selection collapses to ONE
        element and has no ranges, so logic over the whole table is a Python
        loop.

        Indices, not cached row handles: `row |= {...}` rebinds the name it is
        written on to Kathryn's assigned-marker, so a write always names
        `self.table[idx]` afresh and a handle is only ever read from.
        """
        return range(self.rsv_spec.size)

    def read_row_fields(self, src_row: KarrayRef, **overrides) -> dict:
        """One row's fields, read out by name, with some of them replaced.

        The spelling for "copy this row but say something else about two of its
        fields": one write, so nothing depends on the order two writes of equal
        priority happen to be emitted in.
        """
        fields = {name: to_ref(getattr(src_row, name))
                  for name in self.entry_fields if name not in overrides}
        fields.update(overrides)
        return fields

    # --- the policy a subclass owns --------------------------------------------
    def build_issue(self, *args, **kwargs):
        raise NotImplementedError(
            f"{type(self).__name__}.build_issue: which ready entry issues is the "
            f"station's own policy — oldest by `track` out of order, the head in "
            f"order — so a subclass has to say")

    def free_slots(self, dispatch):
        """(all_ok, [(this port has a slot, where)]) — one entry per write
        port, and the aggregate: `all_ok` is the AND over ports of "this lane
        can land here, or it is not aimed here at all", the Rob.free_slots
        shape read per station.

        Takes the dispatch bus because a port is a LANE, fixed to it, and a
        lane may be carrying a µop for another station this cycle — so what an
        earlier port takes here (and therefore what a later one must avoid) is
        only knowable from the lanes themselves.

        Policy too: out of order any free row will do so long as two ports get
        different ones, in order they are the run the allocation pointer names.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.free_slots: where a dispatch lands is the "
            f"station's own policy")

    # --- writes ----------------------------------------------------------------
    def write_entry(self, idx, src_row):
        """Dispatch fills one entry from a wire row of the same shape.

        At the rename rung: an entry is written the instant its µop renames, and
        that write has to beat the same cycle's issue/bypass work on the entry.
        """
        with priority(PRI_RENAME):
            self.table[idx] |= src_row

    def lane_targets_me(self, disp_row):
        """This dispatch lane is carrying a µop, and it is for this station."""
        return to_ref(disp_row.valid) & (to_ref(disp_row.rsv_id) == self.rsv_idx)

    def lanes_for_me(self, dispatch):
        """That answer for every write port, built ONCE.

        One write port per front-end lane: every lane may dispatch in the same
        cycle, and any of them may be aimed at this station. Issue stays
        single — one entry leaves per cycle, to one execution unit.

        Both halves ask — the slot search, to know what an earlier lane takes,
        and the write side, to know whether to take it — and rebuilding it
        would be two comparator trees saying one thing.
        """
        if self._lane_targets_me is None:
            self._lane_targets_me = [self.lane_targets_me(dispatch[port])
                                     for port in range(self.config.fe_lanes)]
        return self._lane_targets_me

    def entry_squashed(self, row, fix_tag):
        """This entry dies on this mispredict: occupied, speculating, and under
        one of the tags being killed.

        One definition, so a station that needs the SURVIVORS reads it back
        rather than restating the predicate and drifting from it.
        """
        return (to_ref(row.valid)
                & to_ref(row.is_spec)
                & ((to_ref(row.spec_tag) & fix_tag) != 0))

    def on_dispatch(self, dispatch):
        """Take every dispatch lane aimed at this station, in one cycle.

        `dispatch` is a lanes-wide wire Karray of this station's shape plus
        `rsv_id` (rsv_helper.build_rsv_dispatch). A lane is taken when it names
        this station AND the station has a free entry to give it — `free_slots`
        hands out a DIFFERENT one per port, so two lanes never collide.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.on_dispatch: where each lane lands is the "
            f"station's own policy")

    def on_issue(self, idx, src_row):
        """One entry leaves for the FU: its contents land in `exec_src` and the
        row frees. `idx` is a plain signal or an OH(...) one-hot — a Karray
        index takes either.

        The speculation pair rides in the row, so the copy carries it as it
        stands — `issue_lane` has already had a tag resolving THIS cycle
        masked out of it, which is `on_suc_pred`'s business, not this one's.

        At PRI_ISSUE, not plain: a complex masks the tag out of `exec_src`
        from the register's PREVIOUS contents, so an equal-priority copy
        could lose to it and a freshly issued entry would take the old
        entry's tag. The row write rides the same rung, and both still lose
        to the dispatch that may claim the freed row this cycle.
        """
        with priority(PRI_ISSUE):
            self.exec_src[0] |= src_row
            self.table[idx]  |= {"valid": 0}

    def on_mis_pred(self, fix_tag):
        """A prediction was wrong: every entry speculating under a killed tag
        goes away, and the issue pip flushes — nothing issues in the squash
        cycle. `fix_tag` is the one-hot mask of what is being squashed."""
        self.issue_meta.flush()
        with priority(PRI_MIS_PRED):
            for row_idx in self.all_row_idxs():
                with zif(self.entry_squashed(self.table[row_idx], fix_tag)):
                    self.table[row_idx] |= {"valid": 0}

    def on_suc_pred(self, suc_tag):
        """A prediction resolved correctly: its tag stops covering anything.

        - an entry stays speculative while any OTHER tag it carries is still
          open, which is what the mask-out says
        - the entry ISSUING this cycle is masked too, on `issue_lane` rather
          than on `exec_src`: the register is written at the edge, so only
          the wire carries the value that is actually landing
        """
        for row_idx in self.all_row_idxs():
            row  = self.table[row_idx]
            left = to_ref(row.spec_tag) & ~suc_tag
            with zif(to_ref(row.valid) & to_ref(row.is_spec)):
                self.table[row_idx] |= {"spec_tag": left,
                                        "is_spec" : left != 0}

        # The entry issuing THIS cycle is still only a wire — `exec_src` holds
        # the PREVIOUS one and is written at the edge — so this lands on
        # `issue_lane`, reading the candidate `pre_issue`, above the plain
        # whole-row copy that drives it. A tag is ONE-HOT (tag_gen), so an
        # entry sits under exactly one and `==` is the whole test; there is
        # no residue to leave behind, which is why the write is a flat 0.
        cand = self.pre_issue[0]
        with priority(PRI_SUC_PRED):
            with zif(cand.is_spec & (cand.spec_tag == suc_tag)):
                self.issue_lane[0] *= {"spec_tag": 0, "is_spec": 0}

    def on_bypass(self, *bypasses: RsvBypass):
        """Writeback broadcasts: a waiting source whose physical index matches
        captures the value and becomes ready."""
        for row_idx in self.all_row_idxs():
            row = self.table[row_idx]
            for atm_operand in self.has_src_arch_operands:
                valid_f  = field_name(VALID,  atm_operand)
                pr_idx_f = field_name(PR_IDX, atm_operand)
                for bypass in bypasses:
                    # A broadcast only wakes sources naming ITS register class:
                    # two PRFs number their entries independently.
                    if bypass.reg_file is not atm_operand.reg_file:
                        continue
                    hit = (to_ref(row.valid)
                           & ~to_ref(getattr(row, valid_f))
                           & (to_ref(getattr(row, pr_idx_f)) == bypass.pr_idx))
                    with zif(hit):
                        self.table[row_idx] |= {
                            valid_f                        : 1,
                            field_name(DATA, atm_operand)  : bypass.data}