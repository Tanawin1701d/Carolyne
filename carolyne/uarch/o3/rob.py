# Rob — the reorder buffer: every in-flight instruction in program order, and
# the commit that retires them into architectural state.
#
# TWO POINTERS AND A COUNT. `alloc_ptr` is where the next instruction lands,
# `com_ptr` the oldest one, and `used_entry_cnt` how many sit between them. The
# count is what tells a full buffer from an empty one, which two pointers of
# the same width cannot; it takes ONE clocked write per cycle from
# `on_update_meta`, the way Prf resolves rename against commit, so allocating
# and retiring in the same cycle cannot lose each other. The depth must be a
# POWER OF TWO: both pointers step modulo the table, so at that size the modulo
# is the register width and no wrap compare is built.
#
# The C++ original indexes its ROB by the RRF pointer, which a per-class PRF
# makes impossible here — this engine renames each register class into its own
# physical file, so the ROB keeps an index space of its own.
#
# COMMIT IN GROUPS, UP TO AND INCLUDING A BARRIER. Lane k retires only if every
# earlier lane in the group retires AND no earlier lane is a branch or a store:
#
#   lane      1    2    3*   4    5    6      (* = branch or store)
#   retires   yes  yes  yes  no   no   no
#
# so a barrier is always the LAST instruction of its group and at most one of
# them retires per cycle — which is what lets the store buffer pop once and the
# predictor update once. It is the C++ `com2Cond = wbFin & ~com1(isBranch) &
# ~com1(storeBit)` written for any number of lanes.
#
# The commit body sits in a `pip` block on the commit stage's arbiter, so a
# mispredict CLEARS the grant and nothing retires that cycle.

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.common import ceil_log2
from carolyne.util import is_power_of_two
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, PR_IDX, WB_REQUIRED,
                                             field_name)
from carolyne.uarch.o3.priority import PRI_MIS_PRED, PRI_RENAME
from carolyne.uarch.o3.reg_arch_mng import RegArchMng
from carolyne.uarch.o3.store_buf import StoreBuf
from carolyne.uarch.o3.rob_helper import (build_rob_table, rob_dest_operands,
                                          rob_entry_shape)


class Rob(Module):
    """The reorder buffer, and the commit stage that drains it."""

    def __init__(self,
                 config       : CPUO3_Config,
                 reg_arch_mng : RegArchMng,
                 store_buf    : StoreBuf,
                 name         : str = "rob"):

        depth = config.rob_depth
        if depth < 2:
            raise ValueError(
                f"Rob: {depth} entry — the buffer is addressed by two pointers, and "
                f"one entry leaves them 0 bits wide")
        if not is_power_of_two(depth):
            raise ValueError(
                f"Rob: {depth} entries — both pointers step modulo the buffer, so the "
                f"depth must be a power of two or every step needs its own wrap compare")
        if config.fe_lanes > depth:
            raise ValueError(
                f"Rob: {config.fe_lanes} front-end lanes into a {depth}-entry buffer — "
                f"a group dispatches whole or not at all, so one that cannot fit in an "
                f"EMPTY buffer could never dispatch")
        if reg_arch_mng.commit_ports != config.commit_lanes:
            raise ValueError(
                f"Rob: {config.commit_lanes} commit lanes against a register "
                f"architecture built with {reg_arch_mng.commit_ports} commit ports — a "
                f"lane IS a port, one returning the physical register the other "
                f"retires, so the two are one number and must be stated as one")

        if not isinstance(store_buf, StoreBuf):
            raise TypeError(
                f"Rob: store_buf must be a StoreBuf, got "
                f"{type(store_buf).__name__} — a store reaches memory ONLY on "
                f"retirement, so the buffer is what commit reports into and a "
                f"core cannot run without one")

        self.config       = config
        self.reg_arch_mng = reg_arch_mng
        self.store_buf    = store_buf
        self.label        = name

        super().__init__()

    @init
    def com_declare(self):

        self.depth        = self.config.rob_depth
        self.commit_lanes        = self.config.commit_lanes
        self.idx_width    = ceil_log2(self.depth)
        # One value more than the depth is representable, so a full buffer is
        # not an empty one: 0..depth INCLUSIVE needs the extra bit.
        self.cnt_width    = self.idx_width + 1
        self.dest_operands = rob_dest_operands(self.config.isa)

        self.table = build_rob_table(self.config, self.label)

        # The commit stage's arbiter — the ROB owns it, and its on_mis_pred
        # binds the squash as the reset, so nothing retires in that cycle.
        self.commit_meta = PipCon(name=f"{self.label}_commit")

        self.alloc_ptr = reg(self.idx_width, f"{self.label}_alloc_ptr")
        self.alloc_ptr.reset(0)
        self.com_ptr   = reg(self.idx_width, f"{self.label}_com_ptr")
        self.com_ptr.reset(0)
        self.used_entry_cnt = reg(self.cnt_width, f"{self.label}_used_entry_cnt")
        self.used_entry_cnt.reset(0)

        # The rows commit reads, one per lane, materialised so the commit block
        # reads a slot instead of folding the table once per field.
        entry_cls, fields = rob_entry_shape(self.config)
        self.com_row = entry_cls(HwComponentType.WIRE, (self.commit_lanes,),
                                 f"{self.label}_com_row", **fields)
        self.commit_ok = [wire(1, f"{self.label}_commit_ok{lane}")
                          for lane in range(self.commit_lanes)]

        # Where each front-end lane allocates. Built on the first free_slots
        # call. ONE room bit for the cycle, not one per lane: the group lands
        # whole or not at all, so there is only one answer to give.
        self.dispatch_fits = wire(1, f"{self.label}_dispatch_fits")
        self.free_idx = [wire(self.idx_width, f"{self.label}_free_idx{port}")
                         for port in range(self.config.fe_lanes)]
        self.want_cnt    = None     # the cycle's popcount of valid lanes
        self._free_built = False

        # PORTS. Allocation and commit both move the count, so each states what
        # it did and on_update_meta commits the one write — the Prf bargain,
        # which is what makes their call order irrelevant.
        self.alloc_cnt  = wire(self.cnt_width, f"{self.label}_alloc_cnt").default(0)
        self.commit_cnt = wire(self.cnt_width, f"{self.label}_commit_cnt").default(0)

    # --- occupancy ----------------------------------------------------------------
    def lane_used(self, lane: int):
        """Lane `lane` of a commit group names a real instruction."""
        return val(self.cnt_width, lane) < self.used_entry_cnt

    def room_left(self):
        """Entries the buffer still has. Both sides of the compare stay inside
        the count's width, which `depth + a group` would not."""
        return val(self.cnt_width, self.depth) - self.used_entry_cnt

    def group_fits(self, wanted):
        """The WHOLE dispatch group fits. A group lands together or not at all,
        so this one answer serves every lane of it."""
        return wanted <= self.room_left()

    # --- dispatch -----------------------------------------------------------------
    def free_slots(self, dispatch):
        """A run from the allocation pointer, one entry per front-end lane.

        Every lane that carries an instruction allocates, so the run compacts
        by how many earlier lanes are valid — the ROB holds program order, and
        a gap in it would be an instruction retiring out of turn.

        ALL OR NOTHING: if the group does not fit whole, no lane of it lands.
        That is one comparison for the cycle rather than one per lane, and it
        is what lets the front end treat a bundle as a bundle — a partial
        dispatch would leave the rest of the group to be re-formed behind it.

        Returns (dispatch_fits, free_idx): ONE room bit for the whole cycle
        beside one index per lane — the shape itself says the group lands
        together or not at all.
        """
        if not self._free_built:
            wants = [to_ref(dispatch[port].valid)
                     for port in range(self.config.fe_lanes)]
            alloc = self.alloc_ptr
            # ONE popcount for the cycle, sized to the count register here:
            # the fit compare and on_dispatch's advance both read it.
            self.want_cnt = sum_cnt(wants, width=self.cnt_width)
            self.dispatch_fits *= self.group_fits(self.want_cnt)
            for port in range(self.config.fe_lanes):
                offset = val(1, 0) if port == 0 else sum_cnt(wants[:port])
                self.free_idx[port] *= alloc if port == 0 else alloc + offset
            self._free_built = True

        return self.dispatch_fits, self.free_idx

    def on_dispatch(self, dispatch):
        """Allocate an entry for every lane carrying an instruction.

        The group lands together or not at all (`free_slots`), so there is no
        hole to guard against here: every lane sees the same answer, and a lane
        carrying nothing simply takes nothing.
        """
        fits, free_idx = self.free_slots(dispatch)
        for port, idx in enumerate(free_idx):
            take = to_ref(dispatch[port].valid) & fits
            with zif(take):
                self.write_entry(to_ref(idx), dispatch[port])

        # Gated ONCE on fits, advancing by the want count free_slots already
        # built — all-or-nothing means the taken count IS the want count, so
        # no second popcount over fits-gated lane bits.
        with zif(fits):
            with priority(PRI_RENAME):
                self.alloc_ptr |= self.alloc_ptr + self.want_cnt
            self.alloc_cnt *= self.want_cnt
        self.on_update_meta()

    def write_entry(self, idx, src_row):
        """Fill one entry. Nothing has written back yet, whatever the bus says."""
        with priority(PRI_RENAME):
            self.table[idx] |= self.read_row_fields(src_row, wb_fin=0)

    def read_row_fields(self, src_row: KarrayRef, **overrides) -> dict:
        """One row's fields by name, with some replaced — one write, so nothing
        depends on the order two writes of equal priority are emitted in."""
        entry_cls, fields = rob_entry_shape(self.config)
        names  = [name for name, _ in entry_cls.__karray_fields__]
        names += [name for name in fields if name not in names]
        out = {name: to_ref(getattr(src_row, name))
               for name in names if name not in overrides}
        out.update(overrides)
        return out

    # --- writeback ----------------------------------------------------------------
    def on_write_back(self, idx):
        """An execution unit finished: that entry may now retire."""
        self.table[idx] |= {"wb_fin": 1}

    # --- commit -------------------------------------------------------------------
    @flow
    def run_commit(self):
        """Retire the head group, inside the commit stage's pip block.

        The ROB's OWN flow: it owns `commit_meta`, so it owns the block that
        runs on it — nobody calls this, gen_flow does.

        NOTHING RETIRES IN A SQUASHED CYCLE, and the arbiter is what says so:
        `on_mis_pred` flushes that arb, which clears the grant and leaves
        this block unfired.
        """
        for lane in range(self.commit_lanes):
            self.com_row[lane] *= self.table[self.com_ptr + lane]

        with pip(self.commit_meta, auto_req=True, auto_restart=True):
            next_may_retire = None
            for lane in range(self.commit_lanes):
                row = self.com_row[lane]
                ok  = self.lane_used(lane) & to_ref(row.wb_fin)
                if next_may_retire is not None:
                    ok = ok & next_may_retire
                self.commit_ok[lane] *= ok
                # A branch or a store retires as the LAST of its group: the
                # store buffer pops once a cycle and so does the predictor.
                next_may_retire = (ok & ~to_ref(row.is_branch)
                                      & ~to_ref(row.is_store))

                # The store's memory write may now go. At most one lane fires
                # (a store is last of its group), so the buffer pops once.
                with zif(ok & to_ref(row.is_store)):
                    self.store_buf.on_commit()

                self._retire(lane, row)

            self.com_ptr    |= self.com_ptr + sum_cnt(self.commit_ok)
            self.commit_cnt *= sum_cnt(self.commit_ok, width=self.cnt_width)

    def _retire(self, lane: int, row):
        """One lane's architectural effect, under TWO different conditions.

        ACTIVE says rename allocated a physical register for that destination,
        so the register goes back to its pool — whether or not anything was
        written into it. The write becoming architectural — the Arf taking the
        value, the rename table dropping the physical register — is gated by
        the record's WB_REQUIRED bit on a DEST_W_REQ core; a plain DEST stores
        no bit and writes on ACTIVE alone.

        The two are not the same question, and freeing on the narrower one
        would leak a register every time an allocated register's write was
        not required.
        """
        # ONE dest per architectural class is the ISA's own rule
        # (_reject_shared_dest_classes), so each operand is its class's one
        # commit answer and the class's port takes exactly one drive per lane.
        for atm_operand in self.dest_operands:
            reg_file = atm_operand.reg_file
            frees_phy_reg = self.commit_ok[lane] & to_ref(
                getattr(row, field_name(ACTIVE, atm_operand)))

            # a plain DEST stores no wb_required: its write asks no
            # permission of the bit, active alone makes it architectural
            if atm_operand.is_write_required:
                writes = frees_phy_reg & to_ref(
                    getattr(row, field_name(WB_REQUIRED, atm_operand)))
            else:
                writes = frees_phy_reg
            pr_idx = to_ref(getattr(row, field_name(PR_IDX, atm_operand)))
            ar_idx = self._arch_index(row, atm_operand)

            with zif(writes):
                prf  = self.reg_arch_mng.prf(reg_file)
                data = to_ref(prf.on_get_entry(pr_idx).data)
                self.reg_arch_mng.arf(reg_file).write    (ar_idx, data  )
                self.reg_arch_mng.rt (reg_file).on_commit(ar_idx, pr_idx)

            self.reg_arch_mng.prf(reg_file).on_commit(lane, frees_phy_reg)

    def _arch_index(self, row, atm_operand):
        """Where this destination retires to. A one-register class stores no
        index — there is one register and it is register 0."""
        if atm_operand.reg_file.index_width:
            return to_ref(getattr(row, field_name(AR_IDX, atm_operand)))
        return val(1, 0)

    # --- the cycle ----------------------------------------------------------------
    def on_update_meta(self):
        """Resolve allocation against commit into ONE write of the count."""
        self.used_entry_cnt |= (self.used_entry_cnt
                           + self.alloc_cnt - self.commit_cnt)

    # --- squash -------------------------------------------------------------------
    def on_mis_pred(self, rob_idx):
        """A prediction was wrong: everything YOUNGER than that entry goes.

        The branch itself stays — it still has to retire — so the tail lands one
        past it and the count becomes the run from the head to it inclusive.
        The head does not move. The commit arb flushes with it, so nothing
        retires in the squashed cycle.
        """
        self.commit_meta.flush()
        with priority(PRI_MIS_PRED):
            self.alloc_ptr |= to_ref(rob_idx) + 1
            self.used_entry_cnt |= (to_ref(rob_idx) - self.com_ptr
                               ).extend(self.cnt_width) + 1
