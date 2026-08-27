# Dispatch — the stage between decode and the back end: it puts each decoded
# lane on the core-wide dispatch bus every reader downstream shares.
#
# - the conversion is ONE k2k assign per lane: Kathryn pairs fields by NAME
#   AND WIDTH and skips the rest (uop_contract §6 reader rule), so the decode
#   row fills exactly the overlap
# - the skipped fields are the RENAME half — pr_idx_<n>, rob_des_idx,
#   is_spec/spec_tag — and Kathryn's skip warning at elaboration is the
#   honest list of what this stage does not fill yet
# - the bus rows are WIRES, driven at WARM time (warm_rsvs): a station's
#   wants read them before the grant; the granted zync is where the readers
#   commit their content into state

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.decode_helper import DecodeEntryBase
from carolyne.uarch.o3.dispatch_helper import build_dispatch, DispatchEntryBase
from carolyne.uarch.o3.operand_field import ACTIVE, AR_IDX, field_name
from carolyne.uarch.o3.reg_arch_mng import collect_arch_dest_atm_oprs


def booking_ok(block):
    """READY-polarity read of a block's over_use: its bookings all fit.

    Works on anything with the port — TagGen and every class's Prf.
    """
    return ~to_ref(block.over_use)


class Dispatch(Module):

    def __init__(self, config: CPUO3_Config):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config = config
        super().__init__()

    @init
    def com_declare(self):
        self.dispatch_bus  = build_dispatch(self.config, name="dispatch")
        self.dispatch_meta = PipCon()

        # DEST slots with an architectural class — what rename books a
        # physical register for.
        self.arch_dest_atm_oprs = collect_arch_dest_atm_oprs(
            self.config.isa, f"dispatch of ISA '{self.config.isa.name}'")

        # every resource this cycle's bundle books is available — the AND of
        # what the warm_* calls return, what the handshake stalls on
        self.ready_to_go = wire(1, "dispatch_ready_to_go")

        self.decode       = None    # the decode stage's rows, from connect()
        self.next_meta    = None    # the consumer's arb, from connect()
        self.reg_arch_mng = None    # ARF/PRF/RT per class, from connect()
        self.tag_gen      = None    # the speculation-tag allocator, from connect()
        self.rob          = None    # the reorder buffer, from connect()
        self.rsvs         = None    # the reservation stations, from connect()


    # warm system means wire connect / no update register typically used for protocol handshake and give promiss data

    def warm_tag_gen(self):
        """Book every lane's speculation tag on the core-wide TagGen — wires only.

        - is_branch = the lane's `valid` & the decode row's `is_branch`, so an
          empty lane consumes no tag
        - the booking lands in self.tag_acquisition, keyed by lane, as
          (is_branch, is_spec, tag) — the request bit beside what the bus's
          is_spec/spec_tag will carry
        - nothing commits here: the counters move on TagGen's update half
        - returns READY: no lane booked a tag the pool has not got
        """
        self.tag_acquisition = {}
        for lane in range(self.config.fe_lanes):
            decode_entry = self.decode[lane]
            is_branch    = to_ref(decode_entry.valid) \
                         & to_ref(decode_entry.is_branch)
            is_spec, tag = self.tag_gen.book_rename(lane, is_branch)
            self.tag_acquisition[lane] = (is_branch, is_spec, tag)
        return booking_ok(self.tag_gen)

    def warm_prfs(self):
        """Book every lane's allocation on its class's PRF — wires only.

        - req = the lane's `valid` & the dest slot's `active_<n>`, straight
          off the decode row
        - the booking lands in self.prf_acquisition, keyed
          (lane, id(atm_opr)), as (req, pr_idx) — the request bit and the
          promised entry the bus will carry
        - nothing commits here: update_prfs (on the grant) is what moves
          free_entry/next_index
        - returns READY: no class's file ran out under the cycle's bookings
        """
        # one dest per class is the ISA's own rule (IsaBase's
        # _reject_shared_dest_classes), so no lane can book a port twice
        self.prf_acquisition = {}
        for lane in range(self.config.fe_lanes):
            decode_entry = self.decode[lane]
            valid        = to_ref(decode_entry.valid)
            for atm_opr in self.arch_dest_atm_oprs:
                prf    = self.reg_arch_mng.prf(atm_opr.reg_file)
                active = to_ref(getattr(decode_entry,
                                        field_name(ACTIVE, atm_opr)))
                req = valid & active
                self.prf_acquisition[(lane, id(atm_opr))] = \
                    (req, prf.book_rename(lane, req))

        ok = val(1, 1)
        for atm_opr in self.arch_dest_atm_oprs:
            ok = ok & booking_ok(self.reg_arch_mng.prf(atm_opr.reg_file))
        return ok



    def warm_rts(self):
        """Register every lane's rename on its class's RT — metas only.

        - req / pr_idx come off prf_acquisition, is_branch / tag off
          tag_acquisition, ar_idx straight off the decode row
        - book_rename only RECORDS the port's metas; RT's on_rename (the
          update half) is what builds the writes from them
        - returns READY, constant 1: registering metas runs out of nothing
        """
        for lane in range(self.config.fe_lanes):
            decode_entry            = self.decode[lane]
            is_branch, is_spec, tag = self.tag_acquisition[lane]
            for atm_opr in self.arch_dest_atm_oprs:
                rt          = self.reg_arch_mng.rt(atm_opr.reg_file)
                req, pr_idx = self.prf_acquisition[(lane, id(atm_opr))]
                # a one-register class stores no ar_idx (index_width 0):
                # there is nothing to choose, that register is 0
                if atm_opr.reg_file.index_width == 0:
                    ar_idx = 0
                else:
                    ar_idx = to_ref(getattr(decode_entry,
                                            field_name(AR_IDX, atm_opr)))
                rt.book_rename(lane, req, is_branch, tag, ar_idx, pr_idx)
        return val(1, 1)

    def warm_rob(self):
        """Ask the ROB where every lane would land — wires only.

        - free_slots reads the DECODE rows' valid bits: the bus's own are
          driven inside the granted zync, and the fit answer must exist
          BEFORE the grant it helps decide
        - the promise lands in self.rob_acquisition as (dispatch_fits,
          free_idx) — the all-or-nothing room bit and one entry per lane,
          the rob_des_idx the bus will carry
        - nothing commits here: update_rob (on the grant) is what writes
          entries and moves the allocation pointer
        - returns READY: the whole bundle fits the buffer
        """
        fits, free_idx = self.rob.free_slots(self.decode)
        self.rob_acquisition = (fits, free_idx)
        return fits

    def warm_rsvs(self):
        """Convert the lanes onto the bus, then ask every station whether
        the cycle's lanes can land — wires only.

        - the conversion runs HERE, not in the granted zync: the bus rows
          are wires, so driving them at warm time is what lets a station's
          wants read valid before the grant they help decide
        - free_slots builds each station's allocation wires and answers
          all_ok: every lane aimed at that station gets an entry, or is not
          aimed there at all
        - nothing commits here: update_rsvs (on the grant) is what writes
          the entries
        - LIMIT: rsv_id now copies from the decode row, but decode still
          writes it 0 — every valid lane names station 0 until the
          µop→station routing rule lands in uop_decode
        - returns READY: the AND of every station's all_ok
        """
        for lane in range(self.config.fe_lanes):
            self.convert_lane(self.decode[lane], self.dispatch_bus[lane])

        ok = val(1, 1)
        for rsv in self.rsvs:
            all_ok, _slots = rsv.free_slots(self.dispatch_bus)
            ok = ok & all_ok
        return ok

    # it is used when everything is good and ready to go to

    def update_tag_gen(self):
        """Commit the cycle's tag bookings on the core-wide TagGen.

        - MUST run inside the granted zync: the trigger on_rename fires is
          what opens TagGen's on_update_meta gate
        """
        self.tag_gen.on_rename()

    def update_prfs(self):
        """Commit each lane's booking on every class's PRF.

        - MUST run inside the granted zync: on_rename's fin write takes the
          grant as its gate there
        - reads the promises warm_prfs kept (book_rename's returned index)
        """
        for lane in range(self.config.fe_lanes):
            for atm_opr in self.arch_dest_atm_oprs:
                prf = self.reg_arch_mng.prf(atm_opr.reg_file)
                req, pr_idx = self.prf_acquisition[(lane, id(atm_opr))]
                prf.on_rename(pr_idx)


    def update_rts(self):
        """Commit each class's registered renames on its RT.

        - MUST run inside the granted zync: the chain overlays and the
          branch snapshots take the grant as their gate there
        - reads the metas warm_rts registered; on_rename walks every port
          itself, so one call per class
        """
        for atm_opr in self.arch_dest_atm_oprs:
            rt = self.reg_arch_mng.rt(atm_opr.reg_file)
            rt.on_rename()

    def update_rob(self):
        """Commit the cycle's allocations on the ROB.

        - MUST run inside the granted zync: the entry writes and the
          pointer advance take the grant as their gate there
        - passes the BUS rows: free_slots already built its wants off the
          decode rows (warm_rob), so on_dispatch reuses those and takes
          each entry's CONTENT off the filled lane
        """
        self.rob.on_dispatch(self.dispatch_bus)

    def update_rsvs(self):
        """Commit the cycle's dispatches on every station.

        - MUST run inside the granted zync: write_entry and the age/pointer
          work take the grant as their gate there
        - passes the BUS rows: free_slots already built its wants and slots
          at warm time (warm_rsvs), so on_dispatch reuses those and takes
          each entry's content off the filled lane
        """
        for rsv in self.rsvs:
            rsv.on_dispatch(self.dispatch_bus)



    @flow
    def transfer(self):

        # the warm half books, and each call answers whether its resource
        # is actually available — the AND is the cycle's go/stall bit
        tag_ok = self.warm_tag_gen()
        prf_ok = self.warm_prfs()
        rt_ok  = self.warm_rts()
        rob_ok = self.warm_rob()
        rsv_ok = self.warm_rsvs()
        self.ready_to_go *= tag_ok & prf_ok & rt_ok & rob_ok & rsv_ok

        with pip(self.dispatch_meta):
            # inside the zync: everything here fires on the grant only, and
            # the handshake itself is gated on ready_to_go — a cycle missing
            # any booked resource stalls instead of transferring
            with zync((self.next_meta, self.ready_to_go)):
                self.update_tag_gen()
                self.update_prfs()
                self.update_rts()
                self.update_rob()
                self.update_rsvs()

    def convert_lane(self,
                     decode_entry  : DecodeEntryBase,
                     dispatch_entry: DispatchEntryBase):
        """One decoded row onto one bus lane, as a single k2k assign.

        - name+width pairing copies valid, pc, npc, uop_idx, is_branch,
          is_store, rsv_id and the operand groups; the rest is SKIPPED with
          Kathryn's warning
        - LIMIT: the skipped fields are rename/allocation's answers — until
          the update_* half fills them, an unfilled wire reads its implicit
          zero
        - `*=`, not `|=`: the bus rows are wires
        """
        dispatch_entry *= decode_entry