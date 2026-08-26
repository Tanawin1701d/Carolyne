# TagGen — the speculation-tag allocator: which tag an in-flight instruction
# carries, and how many tags are still available to hand out.
#
# A tag is ONE-HOT (`next_tag` is sptag_len bits, resets to 1, rotates left), so
# a squash can mask a whole set of speculations with one AND instead of a
# comparison per entry. `free_tag` is the COUNT of tags left, which is why it is
# ceil_log2(sptag_len) bits while the tag itself is sptag_len.
#
# `book_rename` returns (is_spec, tag). The tag is the pointer BEFORE
# rotating, so a branch carries the current tag and the pointer moves past
# it — the relation `on_mis_pred` inverts when it restores
# `next_tag = rot(last_valid_tag)`. A non-branch takes the same tag and leaves
# both counters alone. `is_spec` says the lane dispatches under an open
# speculation: a tag is already out (free_tag below full), or an earlier lane
# of the same cycle books a branch. It reads `free_tag` BEFORE the cycle's
# resolve — legal because the caller stalls rename in any cycle `on_suc_pred`
# fires, so a booking never lands beside a resolve.
#
# Rename and a resolved prediction resolve into ONE clocked write per counter,
# committed by `on_update_meta`: two independent whole-value writes to
# `free_tag` in one cycle would silently lose one.
#
# CALL ORDER MUST NOT MATTER, for any of the three. The ports are WIRES
# declared in `com_declare`; `book_rename` and `on_suc_pred` only DRIVE one and
# `on_update_meta` READS them all, so the three compose in hardware however
# they were spoken. The cost is that the rename PORT COUNT is a construction
# parameter. The resolve side is fixed at ONE port: tags are handed out by
# rotating a single pointer and come back in that order, so at most one can be
# returned per cycle.
#
# A mispredict does NOT join the chain — it is exclusive of the other two, so
# it writes at raised priority and overrides them. `over_use` only REPORTS a
# rename booked with no tag left; `book_rename` still decrements, so the caller
# must stall on it.

from kathryn import *

from carolyne.uarch.common import ceil_log2
from carolyne.uarch.o3.config import CPUO3_Config
# One rung of the engine-wide ladder (priority.py): a mispredict write overrides
# the rename/resolve write of the same cycle.
from carolyne.uarch.o3.priority import PRI_MIS_PRED


class TagGen(Module):

    # mispredict | rename | sucpredict

    def __init__(self,
                 config       : CPUO3_Config,
                 rename_ports : int):
        if isinstance(rename_ports, bool) or not isinstance(rename_ports, int) \
                or rename_ports < 1:
            raise ValueError(f"TagGen: rename_ports must be >= 1, got {rename_ports!r}")
        self.config       = config
        self.rename_ports = rename_ports
        super().__init__()


    @init
    def com_declare(self):

        self.index_width = ceil_log2(self.config.sptag_len)

        self.free_tag = reg(self.index_width, "free_tag_entry")
        self.free_tag.reset(self.config.sptag_len - 1)

        self.next_tag = reg(self.config.sptag_len, "next_tag_entry")
        self.next_tag.reset(1)

        # over used — a rename was booked with no tag left to give it
        self.over_use = wire(1, "tag_over_use")

        # PORTS. Declared once, here, and only DRIVEN by the methods below —
        # which is what makes call order irrelevant (header). An undriven port
        # reads its default, so a lane that books nothing contributes nothing.
        self.branch_port  = [wire(1, "branch_req{}".format(i)).default(0)
                             for i in range(self.rename_ports)]
        # ONE resolve port — tags come back in order, so at most one per cycle.
        self.resolve_port = wire(1, "resolve_ok").default(0)

    # ---- rename ----------------------------------------------------------------
    def book_rename(self, port, is_branch):
        """Hand lane `port` its one-hot tag; a branch also consumes one.

        Returns (is_spec, tag):
        - is_spec: the lane sits under an open speculation — a tag is already
          out (free_tag below full), or a lane before it books a branch this
          cycle
        - tag: the pointer rotated once per BRANCH booked by a lane before it,
          so the lanes of one cycle take consecutive tags and a non-branch
          simply repeats its predecessor's
        It reads the other lanes' port wires, which is legal whether or not
        they are driven yet.
        """
        self.branch_port[port] *= is_branch
        earlier = self.branch_port[:port]
        return (self._spec_before(earlier),
                self._tag_after(earlier, "tag_p{}".format(port)))

    def _spec_before(self, earlier):
        """Open speculation covering a lane behind the bookings in `earlier`.

        - reads free_tag PRE-resolve: the caller stalls rename in a cycle
          on_suc_pred fires, so a booking never sees a same-cycle refill
        """
        outstanding = self.free_tag != (self.config.sptag_len - 1)
        return any_of([outstanding, *earlier])

    def _tag_after(self, earlier, label):
        """The pointer stepped past every booking in `earlier`."""
        tag = self.next_tag
        for i, req in enumerate(earlier):
            # A select, because rotating "by zero" is not a rotate. No width
            # passed: the value is next_tag-wide and rotate_left reads that off.
            tag = mux(req, rotate_left(tag), tag,
                      width = self.config.sptag_len,
                      name  = "{}_s{}".format(label, i))
        return tag

    # ---- a prediction resolves correctly ----------------------------------------
    def on_suc_pred(self, valid):
        """Hand the resolved branch's tag back; `valid` is a 1-bit enable."""
        self.resolve_port *= valid

    # ---- resolve the cycle -------------------------------------------------------
    def on_update_meta(self):
        free, over_terms = self._resolve()
        self.free_tag |= free
        self.next_tag |= self._tag_after(self.branch_port, "tag_next")
        self.over_use *= any_of(over_terms)

    def _resolve(self):
        """The cycle's free-tag count, read off the PORT WIRES rather than off
        anything a caller accumulated.

        The resolve leads STRUCTURALLY — it is wired ahead of the rename
        subtractions — so a branch resolving beside a rename really does hand its
        tag back in time for that rename, whatever order the calls came in.
        Reading wires instead of recorded terms is also what frees this method
        from having to run last.
        """
        free = self.free_tag + self.resolve_port.extend(self.index_width)

        over_terms = []
        for is_branch in self.branch_port:
            # Exhaustion is the borrow out of the subtraction below: none left,
            # yet asked — judged against a pool the resolves have refilled.
            over_terms.append((free == 0).land(is_branch))
            free = free - is_branch.extend(self.index_width)
        return free, over_terms

    # ---- mispredict ---------------------------------------------------------------
    def on_mis_pred(self, last_valid_tag):
        # Exclusive of the rename/resolve write, so priority rather than a stage.
        with priority(PRI_MIS_PRED):
            self.free_tag |= (self.config.sptag_len - 1)
            # Width stated here, unlike book_rename: last_valid_tag comes from a
            # caller, so the check that it really is tag-wide is worth having.
            self.next_tag |= rotate_left(last_valid_tag, width=self.config.sptag_len)
