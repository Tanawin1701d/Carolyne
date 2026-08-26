# Dispatch — the stage between decode and the back end: it puts each decoded
# lane on the core-wide dispatch bus every reader downstream shares.
#
# - the conversion is ONE k2k assign per lane: Kathryn pairs fields by NAME
#   AND WIDTH and skips the rest (uop_contract §6 reader rule), so the decode
#   row fills exactly the overlap
# - the skipped fields are the RENAME half — pr_idx_<n>, rob_des_idx, rsv_id,
#   is_spec/spec_tag, is_branch/is_store — and Kathryn's skip warning at
#   elaboration is the honest list of what this stage does not fill yet
# - the bus rows are WIRES: a lane means something only in the grant cycle

from kathryn import *
from kathryn.signal import to_ref

from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.decode_helper import DecodeEntryBase
from carolyne.uarch.o3.dispatch_helper import build_dispatch, DispatchEntryBase
from carolyne.uarch.o3.operand_field import ACTIVE, field_name
from carolyne.uarch.o3.reg_arch_mng import collect_arch_dest_atm_oprs


class Dispatch(Module):

    def __init__(self, config: CPUO3_Config):
        # Plain-Python configuration only, set BEFORE super().__init__():
        # that call runs the @init methods, which read these fields.
        self.config = config
        super().__init__()

    @init
    def com_declare(self):
        self.dispatch      = build_dispatch(self.config, name="dispatch")
        self.dispatch_meta = PipCon()

        # DEST slots with an architectural class — what rename books a
        # physical register for.
        self.arch_dest_atm_oprs = collect_arch_dest_atm_oprs(
            self.config.isa, f"dispatch of ISA '{self.config.isa.name}'")

        self.decode       = None    # the decode stage's rows, from connect()
        self.next_meta    = None    # the consumer's arb, from connect()
        self.reg_arch_mng = None    # ARF/PRF/RT per class, from connect()


    # warm system means wire connect / no update register typically used for protocol handshake and give promiss data
    def warm_prfs(self):
        """Book every lane's allocation on its class's PRF — wires only.

        - req = the lane's `valid` & the dest slot's `active_<n>`, straight
          off the decode row
        - the booking lands in self.prf_acquisition, keyed
          (id(atm_opr), lane), as (req, pr_idx) — the request bit and the
          promised entry the bus will carry
        - nothing commits here: update_prfs (on the grant) is what moves
          free_entry/next_index
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
                self.prf_acquisition[(id(atm_opr), lane)] = \
                    (req, prf.book_rename(lane, req))

        def war

    def warm_rts(self):
        pass

    def warm_rob(self):
        pass

    def warm_rsvs(self):
        pass

    # it is used when everything is good and ready to go to

    def update_prfs(self):
        """Commit each lane's booking on every class's PRF.

        - MUST run inside the granted zync: on_rename's fin write takes the
          grant as its gate there
        - reads the promises warm_prfs kept (book_rename's returned index)
        """
        for lane in range(self.config.fe_lanes):
            for atm_opr in self.arch_dest_atm_oprs:
                prf = self.reg_arch_mng.prf(atm_opr.reg_file)
                req, pr_idx = self.prf_acquisition[(id(atm_opr), lane)]
                prf.on_rename(pr_idx)

    def update_rts(self):
        pass

    def update_rob(self):
        pass

    def update_rsvs(self):
        pass



    @flow
    def transfer(self):

        #
        self.warm_prfs()
        self.warm_rts()
        self.warm_rob()
        self.warm_rsvs()

        with pip(self.dispatch_meta):
            # inside the zync: everything here fires on the grant only
            with zync(self.next_meta):
                self.update_prfs()
                self.update_rts()
                self.update_rob()
                self.update_rsvs()
                for lane in range(self.config.fe_lanes):
                    self.convert_lane(self.decode[lane], self.dispatch[lane])

    def convert_lane(self,
                     decode_entry  : DecodeEntryBase,
                     dispatch_entry: DispatchEntryBase):
        """One decoded row onto one bus lane, as a single k2k assign.

        - name+width pairing copies valid, pc, npc, uop_idx and the operand
          groups; the rest is SKIPPED with Kathryn's warning
        - LIMIT: the skipped fields are rename/allocation's answers — until
          the update_* half fills them, an unfilled wire reads its implicit
          zero
        - `*=`, not `|=`: the bus rows are wires
        """
        dispatch_entry *= decode_entry