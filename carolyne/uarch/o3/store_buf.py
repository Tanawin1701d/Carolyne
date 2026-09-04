# StoreBuf — the store half of the load/store queue: every executed store
# waits here until the ROB retires it, and only then reaches memory. Loads
# read AROUND it through search_newest (store-to-load forwarding).
#
# THREE POINTERS walk one circular table of `st_buf_depth` entries. Each
# only ever moves FORWARD, by one, wrapping on the register width — which is
# the modulo only because the depth is a power of two (config refuses else):
#
#             slot 0    slot 1    slot 2    slot 3    slot 4    slot 5
#           +--------+--------+--------+--------+--------+--------+
# busy      |   0    |   1    |   1    |   1    |   1    |   0    |
# complete  |   -    |   1    |   1    |   0    |   0    |   -    |
# is_spec   |   -    |   0    |   0    |   1    |   1    |   -    |
# spec_tag  |   -    |  0000  |  0000  |  0010  |  0010  |   -    |
# mem_addr  |   -    |  0x40  |  0x41  |  0x80  |  0x81  |   -    |
# data      |   -    |  'A'   |  'B'   |  'C'   |  'D'   |   -    |
#           +--------+--------+--------+--------+--------+--------+
#                        ^                 ^                 ^
#                     ret_ptr           com_ptr          alloc_ptr
#                   \____ ____/       \____ ____/       \__ ... __/
#                        v                 v                 v
#                 ret..com: the ROB   com..alloc: EXECUTED  alloc..ret: FREE
#                 RETIRED these, so   but the ROB has not   (wraps round
#                 the memory write    reached them yet —    to ret_ptr)
#                 may go now          still squashable
#
#   on_new_entry  pushes at alloc_ptr  — a store finished executing
#   on_commit     advances com_ptr     — the ROB retired it (complete=1)
#   run_retire    pops at ret_ptr      — one memory write per cycle
#
# So a slot's life is alloc -> com -> ret, and the busy region is the run
# ret..alloc. FULL is alloc == ret with that slot still busy. Slots 3 and 4
# above are the ones a squash can still kill (is_spec, and their spec_tag
# matching the fix mask); 1 and 2 are past the ROB and safe.
#
# Correctness leans on the LS station issuing IN ORDER (RsvIOR): entries are
# then program-older than any load executing after them, which is what makes
# search_newest's answer THE newest older store.

from kathryn        import *
from kathryn.signal import to_ref

from carolyne.uarch.common          import ceil_log2
from carolyne.uarch.o3.common_field import SpecLane
from carolyne.uarch.o3.config       import CPUO3_Config
from carolyne.uarch.o3.easy_mem     import EasyMem
from carolyne.uarch.o3.priority     import PRI_MIS_PRED, PRI_SUC_PRED


class StBufEntry(Karray):
    busy     = kaf(1)     # holds a store not yet written to memory
    complete = kaf(1)     # the ROB retired it — memory write may go
    is_spec  = kaf(1)     # still under an open speculation
    spec_tag = kaf()      # the tags it speculates under (mask)
    mem_addr = kaf()      # WORD address in the data memory
    data     = kaf()      # the full word to write


class StoreBuf(Module):
    """The committed-store queue between the execution unit and memory."""

    def __init__(self, config: CPUO3_Config, data_mem: EasyMem,
                 name: str = "st_buf"):
        self.config   = config
        self.data_mem = data_mem
        self.label    = name
        super().__init__()

    @init
    def com_declare(self):
        depth          = self.config.st_buf_depth
        self.depth     = depth
        self.ptr_width = ceil_log2(depth)

        # One row per entry; the three call-site widths come from the machine
        # and the memory, so one buffer class serves any config:
        #
        #   busy complete is_spec  spec_tag      mem_addr        data
        #    1      1        1     sptag_len   index_width   data_width
        #
        # reset clears the three OCCUPANCY bits only — a row powers up empty,
        # and its address/data are don't-care until something claims it.
        self.table = StBufEntry(HwComponentType.REG, (depth,), self.label,
                                spec_tag = self.config.sptag_len,
                                mem_addr = self.data_mem.index_width,
                                data     = self.data_mem.data_width)
        self.table.reset(busy=0, complete=0, is_spec=0)

        # The speculation pair of the store landing THIS cycle, and the place
        # on_suc_pred OVERRIDES it: on_new_entry drives it, the resolve masks
        # it at PRI_SUC_PRED, and the row write reads it — so a tag resolving
        # in the same cycle never reaches the table.
        self.spec_overrider = SpecLane(HwComponentType.WIRE, (1,),
                                       f"{self.label}_spec_ovr",
                                       spec_tag=self.config.sptag_len)

        self.alloc_ptr = reg(self.ptr_width, f"{self.label}_alloc_ptr")
        self.alloc_ptr.reset(0)
        self.com_ptr = reg(self.ptr_width, f"{self.label}_com_ptr")
        self.com_ptr.reset(0)
        self.ret_ptr = reg(self.ptr_width, f"{self.label}_ret_ptr")
        self.ret_ptr.reset(0)

    # --- one-line facts -----------------------------------------------------------
    def is_full(self):
        return (self.alloc_ptr == self.ret_ptr) \
             & self.table[self.alloc_ptr].busy

    # --- the events ---------------------------------------------------------------
    def on_new_entry(self, is_spec, spec_tag, mem_addr, data):
        """An executed store lands at the tail; call in the granted scope.

        - complete stays 0: only the ROB's retirement (on_commit) sets it
        - the speculation pair is the CALLER's record's — the engine reads
          it off the stage record (ExecUnitO3.lsq_push_store) — but it goes
          through `spec_overrider`, so a tag resolving in THIS cycle is masked
          out of it before the row write reads it. Reading the caller's
          register directly would store a tag already resolved.
        """
        self.spec_overrider[0] *= {"is_spec": is_spec, "spec_tag": spec_tag}

        spec_ovr = self.spec_overrider[0]
        self.table[self.alloc_ptr] |= {"busy"    : 1,
                                       "complete": 0,
                                       "is_spec" : to_ref(spec_ovr.is_spec),
                                       "spec_tag": to_ref(spec_ovr.spec_tag),
                                       "mem_addr": mem_addr,
                                       "data"    : data}
        self.alloc_ptr |= self.alloc_ptr + 1

    def on_commit(self):
        """The ROB retired the store at com_ptr: memory write may now go.
        Call in the commit scope, gated on the lane's is_store."""
        self.table[self.com_ptr] |= {"complete": 1}
        self.com_ptr             |= self.com_ptr + 1

    def search_newest(self, mem_addr):
        """Store-to-load forwarding: the NEWEST busy store at that address.

        ONE reduce read (the C++ findMBO_BIDX shape): the comparison tree
        is built once and the winning ROW comes back whole, instead of a
        chain of `depth` muxes each re-deciding the same question.

        - returns (hit, data); a miss reads memory instead (caller's mux)
        - the hit is RE-EVALUATED on the winner rather than folded up: the
          tree always yields some row, and only the winner's own predicate
          says whether it is a real match
        """
        # The caller's address may be wider than the memory's index; the
        # compare runs at the stored width (a write truncates the same way).
        addr  = wire(self.data_mem.index_width, f"{self.label}_search_addr")
        addr *= mem_addr

        def pick_newest(lhs, rhs, level):
            """One node: which subtree holds the newer matching store.

            A hit beats a miss. Between two hits the one on the NEW side of
            the wrap wins; inside one side the fold's own ascending order
            leaves the higher index (the newer store) standing.
            """
            lhs_hit, lhs_pre_wrap = self._search_terms(lhs, addr)
            rhs_hit, rhs_pre_wrap = self._search_terms(rhs, addr)
            # The expression only ever says "take LHS"; everything else
            # falls through to RHS, which is what makes it short:
            #
            #   term 1  lhs_hit & ~rhs_hit
            #           only LHS matched, so it wins by default
            #   term 2  both matched, and LHS is post-wrap while RHS is
            #           pre-wrap — LHS is in the NEWER run, so it wins
            #
            # Every other case wants RHS and gets it for free:
            #   RHS matched alone           -> RHS (correct)
            #   both matched, SAME run      -> RHS, and it is the newer one
            #                                  because the fold pairs
            #                                  ascending indices, so RHS
            #                                  always covers the higher half
            #   both matched, LHS pre-wrap  -> RHS, which is post-wrap
            #   NEITHER matched             -> RHS, an arbitrary row; the
            #                                  caller re-tests the winner's
            #                                  own predicate and reports miss
            pick_lhs = ((lhs_hit & ~rhs_hit)
                        | (lhs_hit & rhs_hit & ~lhs_pre_wrap & rhs_pre_wrap))
            return pick_lhs, {
                "search_hit"     : mux(pick_lhs, lhs_hit, rhs_hit, width=1),
                "search_pre_wrap": mux(pick_lhs, lhs_pre_wrap,
                                                 rhs_pre_wrap, width=1)}

        row = self.table[pick_newest]
        return (to_ref(row.busy) & (to_ref(row.mem_addr) == addr),
                to_ref(row.data))

    def _search_terms(self, view, addr):
        """A subtree's answer: (does it hold a match, is that match PRE-WRAP).

        `pre_wrap` is which of the two runs the wrap cuts the ring into the
        entry belongs to — `alloc_ptr <= idx`, so an entry at or past the
        tail is in the older run and one below the tail is in the newer one.
        That, not the raw index, is what orders two entries by age.

        A leaf has neither answer yet and computes both — the per-row
        augmentation the C++ does before its reduce; a node reads them back
        off the extras rather than rebuilding the compare.
        """
        if "search_hit" in view.fields:
            return view.fields["search_hit"], view.fields["search_pre_wrap"]
        hit = view.fields["busy"] & (view.fields["mem_addr"] == addr)
        return hit, self.alloc_ptr <= view.indices[0]

    # --- squash / resolve -----------------------------------------------------------
    def on_mis_pred(self, fix_tag):
        """Kill the speculating stores; the survivors stay a contiguous run.

        The tail lands at ret + the survivor count (the RsvIOR sum_cnt
        bargain — the C++ original recomputed it with bit-pattern searches);
        com_ptr needs no repair, a committed store is never speculative.
        """
        survivors = []
        with priority(PRI_MIS_PRED):
            for row_idx in range(self.depth):
                row      = self.table[row_idx]
                squashed = (to_ref(row.busy) & to_ref(row.is_spec)
                            & ((to_ref(row.spec_tag) & fix_tag) != 0))
                survivors.append(to_ref(row.busy) & ~squashed)
                with zif(squashed):
                    self.table[row_idx] |= {"busy": 0}
            self.alloc_ptr |= self.ret_ptr \
                          + sum_cnt(survivors).extend(self.ptr_width)

    def on_suc_pred(self, suc_tag):
        """The resolved tag stops covering anything — the RsvBase mask-out.

        The store PUSHED this cycle is masked too, on `spec_overrider` rather
        than on the table: its row is written at the edge, so the wire is
        the only place the value it will take can still be changed.
        """
        for row_idx in range(self.depth):
            row  = self.table[row_idx]
            left = to_ref(row.spec_tag) & ~suc_tag
            with zif(to_ref(row.busy) & to_ref(row.is_spec)):
                self.table[row_idx] |= {"spec_tag": left,
                                        "is_spec" : left != 0}

        # a tag is ONE-HOT, so an entry sits under it or does not
        spec_ovr_row = self.spec_overrider[0]
        with priority(PRI_SUC_PRED):
            with zif(spec_ovr_row.is_spec
                     & (spec_ovr_row.spec_tag == suc_tag)):
                self.spec_overrider[0] *= {"is_spec": 0, "spec_tag": 0}

    # --- retire to memory -----------------------------------------------------------
    @flow
    def run_retire(self):
        """The head's committed store reaches memory, one per cycle.

        StoreBuf's own flow, unconditional: the zif is the gate, so an
        empty or not-yet-complete head writes nothing and moves nothing.
        """
        head = self.table[self.ret_ptr]
        with zif(to_ref(head.busy) & to_ref(head.complete)):
            self.data_mem.write(0, to_ref(head.mem_addr), to_ref(head.data))
            self.table[self.ret_ptr] |= {"busy": 0, "complete": 0}
            self.ret_ptr |= self.ret_ptr + 1
