# Dispatch — the stage between decode and the back end: it puts each decoded
# lane on the core-wide dispatch bus every reader downstream shares.
#
# - the conversion is ONE k2k assign per lane: Kathryn pairs fields by NAME
#   AND WIDTH and skips the rest (uop_contract §6 reader rule), so the decode
#   row fills exactly the overlap
# - the k2k skips are the RENAME half, and every one is filled beside the
#   copy from the warm promises: rob_des_idx (warm_rob), the dest pr_idx_<n>
#   (warm_prfs), is_spec/spec_tag (warm_tag_gen), each arch source's
#   valid/data/pr_idx (rename_src_operand's RT/Arf read) — the skip warning
#   at elaboration lists the COPY's skips, not unfilled fields
# - the bus rows are WIRES, driven at WARM time (warm_rsvs): a station's
#   wants read them before the grant; the granted zync is where the readers
#   commit their content into state

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.o3.common_field import IS_SPEC, ROB_DES_IDX, SPEC_TAG
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.dispatch_helper import build_dispatch
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, DATA, PR_IDX,
                                             VALID, field_name,
                                             named_atomic_operands)
from carolyne.uarch.o3.priority import PRI_RENAME
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

        # SRC slots with an architectural class — what the rename READ
        # (rename_src_operand's RT/Arf lookup) serves.
        self.arch_src_atm_oprs = tuple(
            atm_opr for atm_opr in named_atomic_operands(
                self.config.isa, f"dispatch of ISA '{self.config.isa.name}'")
            if atm_opr.is_src and atm_opr.has_arch)

        # every resource this cycle's bundle books is available — the AND of
        # what the warm_* calls return, what the handshake stalls on
        self.ready_to_go = wire(1, "dispatch_ready_to_go")

        self.decode       = None    # the decode stage's rows, from connect()
        self.next_meta    = None    # the consumer's arb, from connect()
        self.reg_arch_mng = None    # ARF/PRF/RT per class, from connect()
        self.tag_gen      = None    # the speculation-tag allocator, from connect()
        self.rob          = None    # the reorder buffer, from connect()
        self.rsvs         = None    # the reservation stations, from connect()

    # retrieve data you want
    def connect(self, decoder, next_meta, reg_arch_mng, tag_gen, rob, rsvs):
        """Fill the stage's slots: the decoded rows this stage converts, the
        arb its granted transfer runs against, and every block the warm/
        update halves book on."""
        self.decode       = decoder.decode
        self.next_meta    = next_meta
        self.reg_arch_mng = reg_arch_mng
        self.tag_gen      = tag_gen
        self.rob          = rob
        self.rsvs         = tuple(rsvs)

    def on_mis_pred(self):
        # a squash empties the stage: clear the grant, the pip auto-restarts
        self.dispatch_meta.flush()

    def on_suc_pred(self):
        # a resolve stalls the stage for the cycle: a booking must never land
        # beside a resolve (tag_gen's pre-resolve pool read would go stale)
        self.dispatch_meta.stall()

        # no need to override the spectag and is_spec because I is stalled already


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
            self.convert_lane(lane)

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

        with pip(self.dispatch_meta, auto_restart=True):
            # inside the zync: everything here fires on the grant only, and
            # the handshake itself is gated on ready_to_go — a cycle missing
            # any booked resource stalls instead of transferring
            with zync((self.next_meta, self.ready_to_go)):
                self.update_tag_gen()
                self.update_prfs()
                self.update_rts()
                self.update_rob()
                self.update_rsvs()

    def convert_lane(self, lane: int):
        """One decoded row onto one bus lane.

        - the k2k assign: name+width pairing copies valid, pc, npc, uop_idx,
          is_branch, is_store, rsv_id and the operand groups; the rest is
          SKIPPED with Kathryn's warning
        - the k2k-skipped fields are dispatch's OWN answers, written beside
          the copy from the warm promises: rob_des_idx (warm_rob's entry for
          this lane) and is_spec/spec_tag (warm_tag_gen's booking) in the
          promised_fields write, then per operand — each dest slot by
          rename_dest_operand (warm_prfs' promised register), each arch
          source by rename_src_operand (the RT/Arf read). Every write names
          a FRESH selection (an augmented assign rebinds its handle) and a
          field the others skipped — no field driven twice
        - `*=`, not `|=`: the bus rows are wires
        """

        # normal update
        self.dispatch_bus[lane] *= self.decode[lane]
        # convert more data
        _fits, free_idx = self.rob_acquisition
        _is_branch, is_spec, tag = self.tag_acquisition[lane]
        promised_fields = {ROB_DES_IDX: free_idx[lane],
                           IS_SPEC    : is_spec,
                           SPEC_TAG   : tag}
        self.dispatch_bus[lane] *= promised_fields

        # manage dispatch bus for source operand
        for atm_opr in self.arch_src_atm_oprs:
            self.rename_src_operand(lane, atm_opr)
        # manage dispatch bus for des operand
        for atm_opr in self.arch_dest_atm_oprs:
            self.rename_dest_operand(lane, atm_opr)

    def rename_dest_operand(self, lane: int, atm_opr):
        """Fill one dest slot's rename half on the bus — the promised
        physical register.

        - warm_prfs' booking for (lane, dest), written under the pr_idx_<n>
          name the bus carries it as; the request bit stays behind — whether
          the promise is consumed is the entry's active_<n> business
        - its own `*=` on a fresh selection, legal beside the other writes:
          nothing else drives a dest pr_idx
        """
        _req, pr_idx = self.prf_acquisition[(lane, id(atm_opr))]
        self.dispatch_bus[lane] *= {field_name(PR_IDX, atm_opr): pr_idx}

    def rename_src_operand(self, lane: int, atm_opr):
        """Fill one arch source slot's rename half on the bus — the RT read.

        - an INACTIVE slot is not rename's business: every path carries the
          `active` term and fills nothing the µop does not read
        - a value already in hand (decode's valid_<n>: an immediate) keeps
          exactly what the copy put there
        - active and NOT renamed: the committed value IS architectural
          state, so valid_<n>=1 and data_<n> reads the Arf (a const
          register reads its constant)
        - active and renamed splits on the PRF entry's fin: already written
          back -> the value is read straight out of the PRF (valid_<n>=1,
          data_<n> = storage data); still in flight -> valid stays as
          decoded and pr_idx_<n> carries the RT's physical index, what the
          station wakes on
        - lane k reads the RT state AFTER earlier lanes' renames and BEFORE
          its own (Rt.read_rename); an unrenamed class lives in the Arf
          and nowhere else
        - at PRI_RENAME: valid/data overlay the k2k copy's own writes, the
          one-priority-per-layer rule
        """
        decode_entry = self.decode[lane]
        arf     = self.reg_arch_mng.arf(atm_opr.reg_file)
        # the slot's own valid_<n> off the decode row — NOT the lane's valid
        dec_opr_valid = to_ref(getattr(decode_entry, field_name(VALID, atm_opr)))
        active  = to_ref(getattr(decode_entry, field_name(ACTIVE, atm_opr)))
        # a one-register class stores no ar_idx (index_width 0): there is
        # nothing to choose, that register is 0
        if atm_opr.reg_file.index_width == 0:
            ar_idx = 0
        else:
            ar_idx = to_ref(getattr(decode_entry, field_name(AR_IDX, atm_opr)))
        arch_value = arf.read(ar_idx)

        if not atm_opr.reg_file.renamed:
            with priority(PRI_RENAME):
                with zif(~dec_opr_valid & active):
                    self.dispatch_bus[lane] *= {
                        field_name(VALID, atm_opr): 1,
                        field_name(DATA, atm_opr) : arch_value}
            return

        rt  = self.reg_arch_mng.rt(atm_opr.reg_file)
        prf = self.reg_arch_mng.prf(atm_opr.reg_file)
        renamed, prf_idx = rt.read_rename(lane, ar_idx)
        prf_entry = prf.on_get_entry(prf_idx)
        prf_fin   = to_ref(prf_entry.fin)

        # the slot has no value in hand and the µop reads it: rename answers
        needs_value = ~dec_opr_valid & active
        # the value exists somewhere readable NOW — the Arf (not renamed) or
        # a written-back PRF entry — and the mux says which one hands it over
        value_ready = ~renamed | prf_fin
        ready_value = mux(renamed, to_ref(prf_entry.data), arch_value)

        with priority(PRI_RENAME):
            with zif(needs_value):
                with zif(value_ready):
                    self.dispatch_bus[lane] *= {
                        field_name(VALID, atm_opr): 1,
                        field_name(DATA, atm_opr) : ready_value}
                # still in flight: wait on the physical index
                with zelse():
                    self.dispatch_bus[lane] *= {
                        field_name(PR_IDX, atm_opr): prf_idx}

