# TagGen — the speculation-tag allocator: which tag an in-flight instruction
# carries, and how many tags are still available to hand out.
#
# A tag is ONE-HOT (`next_tag` is sptag_len bits, resets to 1, rotates left), so
# a squash can mask a whole set of speculations with one AND instead of a
# comparison per entry. `free_tag` is the COUNT of tags left, which is why it is
# ceil_log2(sptag_len) bits while the tag itself is sptag_len.
#
# Decisions (2026-08-17):
# - `book_rename` returns the tag BEFORE rotating, so a branch carries the
#   current tag and the pointer moves past it. That is the relation
#   `on_mis_pred` inverts — it restores `next_tag = rot(last_valid_tag)` — and
#   the two would disagree under the other convention.
# - A non-branch changes nothing: it takes the same tag and leaves both counters
#   alone. `is_branch` is 1 bit, so the free-count step is a subtraction of the
#   extended bit and needs no select; the tag pointer does need one, because a
#   rotate has no "by zero" form that is also a rotate.
# - Rename and a resolved prediction resolve into ONE clocked write per counter,
#   committed by `on_update_meta` — the same structure Prf uses, and for the same
#   reason: two independent whole-value writes to `free_tag` in one cycle would
#   silently lose one. The class comment reads the three events as exclusive, but
#   this costs nothing if they never overlap and is the only thing that makes
#   them free to overlap later.
# - CALL ORDER MUST NOT MATTER — for ANY of the three, including which one runs
#   last, exactly as in Prf and by exactly the same means. The ports are WIRES
#   declared in `com_declare`; `book_rename` and `on_suc_pred` only DRIVE one,
#   and `on_update_meta` READS them all. A wire read before it is driven still
#   connects, because these are netlist nodes and not values, so the three
#   compose in hardware where the order they were spoken in cannot be observed.
#   It also means `book_rename` can still return its tag: the tag for a lane is
#   the pointer stepped past every EARLIER lane's port wire, which exists from
#   declaration whether or not that lane has been booked yet.
# - The cost is that the rename PORT COUNT is a construction parameter, since a
#   declared network cannot discover its width from how many times a method was
#   called. The RESOLVE side needs no such parameter: it is fixed at ONE port.
#   Tags are handed out by rotating a single pointer and come back in that same
#   order, so at most one can be returned per cycle — a second resolve port would
#   be describing a machine this allocator cannot express. That also drops the
#   `sum_cnt` on the resolve side to a plain `extend`.
# - A mispredict does NOT join the chain: it is exclusive of the other two, so
#   it writes at raised priority and overrides them.
# - `over_use` reports a rename booked with no tag left. Like Prf's, it only
#   REPORTS — `book_rename` still decrements — so the caller must stall on it.

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

        Returns the tag that lane carries: the pointer rotated once per BRANCH
        booked by a lane before it, so the lanes of one cycle take consecutive
        tags and a non-branch simply repeats its predecessor's. It reads the
        other lanes' port wires, which is legal whether or not they are driven
        yet.
        """
        self.branch_port[port] *= is_branch
        return self._tag_after(self.branch_port[:port], "tag_p{}".format(port))

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
