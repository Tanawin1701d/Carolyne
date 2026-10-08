# BTB + bimodal: a direct-mapped branch target buffer whose entries each hold a
# 2-bit saturating counter. A lane is predicted taken when its pc hits an
# entry whose counter is 2 or 3, and the predicted next pc is the stored target.
#
#   | tag | index | align |      the pc, high bits first
#
#   predict      every lane reads the table at its own pc (combinational)
#   on_resolve   the branch unit's outcome updates the entry of that pc:
#                taken      -> allocate (counter 2) or count up, store the target
#                not taken  -> count down on a hit; a miss allocates nothing
#
# The record carries nothing (meta_fields is empty): on_resolve finds the entry
# again from the pc the branch station already carries.
#
# LIMIT: the table is updated at resolve, not at commit. The branch station
# issues in order and a squash kills only younger µops, so a wrong-path
# branch never resolves; but a resolved branch that is later squashed by an
# OLDER one still trained the table.

from __future__ import annotations

from dataclasses import dataclass
from typing      import TYPE_CHECKING, Sequence, Tuple

from kathryn        import HwComponentType, Karray, dbg, init, kaf, mux, val, zif
from kathryn.signal import to_ref

from carolyne.debug.sim            import KarrayProbe
from carolyne.uarch.common.hw_util import ceil_log2
from carolyne.uarch.o3.bp.bp_base  import BpBase, BpOutcome, BpPrediction
from carolyne.uarch.o3.bp.bp_spec  import BpSpec
from carolyne.util.bit_checking    import is_power_of_two

if TYPE_CHECKING:
    from carolyne.uarch.o3.config import CPUO3_Config

COUNTER_BITS  = 2
COUNTER_MAX   = (1 << COUNTER_BITS) - 1
COUNTER_ALLOC = 2                   # weakly taken: a new entry predicts taken once

# BtbEntry's field names, for the string-keyed writes in on_resolve
BTB_VALID   = "valid"
BTB_TAG     = "tag"
BTB_TARGET  = "target"
BTB_COUNTER = "counter"


@dataclass(frozen=True)
class BtbBimodalSpec(BpSpec):
    entries : int = 32              # table rows; a power of two >= 2

    def __post_init__(self) -> None:
        if (isinstance(self.entries, bool) or not isinstance(self.entries, int)
                or self.entries < 2 or not is_power_of_two(self.entries)):
            raise ValueError(
                f"BtbBimodalSpec: entries must be a power of two >= 2, got {self.entries!r}")

    def meta_fields(self, config: CPUO3_Config) -> tuple:  return ()
    def build      (self, config: CPUO3_Config) -> BpBase: return BtbBimodalBp(config, self)


class BtbEntry(Karray):
    valid   = kaf(1)
    tag     = kaf()
    target  = kaf()
    counter = kaf(COUNTER_BITS)


class BtbBimodalBp(BpBase):
    """Direct-mapped BTB, a 2-bit counter per entry."""

    may_predict_taken = True

    def __init__(self, config: CPUO3_Config, spec: BtbBimodalSpec):
        pc_width        = config.isa.pc_width
        self.align_bits = config.isa.pc_align_bits
        self.index_bits = ceil_log2(spec.entries)
        self.tag_bits   = pc_width - self.index_bits - self.align_bits
        if self.tag_bits < 1:
            raise ValueError(
                f"BtbBimodalSpec: {spec.entries} entries leave no tag bits in a "
                f"{pc_width}-bit pc")
        self._resolve_built = False
        super().__init__(config, spec)

    @init
    def com_declare(self):
        self.table = BtbEntry(HwComponentType.REG, (self.spec.entries,), "btb",
                              tag    = self.tag_bits,
                              target = self.config.isa.pc_width)
        self.table.reset(valid=0)

    # --- the pc split -----------------------------------------------------------
    def index_of(self, pc): return to_ref(pc)[self.align_bits + self.index_bits - 1, self.align_bits]
    def tag_of  (self, pc): return to_ref(pc)[self.config.isa.pc_width - 1, self.align_bits + self.index_bits]

    def hit_of(self, entry, pc):
        return to_ref(entry.valid) & (to_ref(entry.tag) == self.tag_of(pc))

    # --- the contract -------------------------------------------------------------
    def predict(self, lane_pcs: Sequence) -> Tuple[BpPrediction, ...]:
        ilen        = self.config.isa.ilen_bytes
        predictions = []
        for pc in lane_pcs:
            entry = self.table[self.index_of(pc)]
            taken = self.hit_of(entry, pc) & to_ref(entry.counter)[COUNTER_BITS - 1]
            predictions.append(BpPrediction(taken, mux(taken, to_ref(entry.target), pc + ilen), {}))
        return tuple(predictions)

    def on_resolve(self, outcome: BpOutcome) -> None:
        """Train the entry of the resolved pc. Built once: one branch unit."""
        if self._resolve_built:
            raise ValueError(
                "BtbBimodalBp.on_resolve: a second branch unit would write the "
                "table at the same priority; this predictor takes one")
        self._resolve_built = True

        index   = self.index_of(outcome.pc)
        entry   = self.table[index]
        hit     = self.hit_of(entry, outcome.pc)
        counter = to_ref(entry.counter)
        count_up   = mux(counter == COUNTER_MAX, val(COUNTER_BITS, COUNTER_MAX), counter + 1)
        count_down = mux(counter == 0,           val(COUNTER_BITS, 0),           counter - 1)

        with zif(outcome.taken):
            self.table[index] |= {BTB_VALID  : 1,
                                  BTB_TAG    : self.tag_of(outcome.pc),
                                  BTB_TARGET : outcome.target,
                                  BTB_COUNTER: mux(hit, count_up, val(COUNTER_BITS, COUNTER_ALLOC))}
        with zif(~outcome.taken & hit):
            self.table[index] |= {BTB_COUNTER: count_down}

    @dbg
    def dbg_probes(self):
        self.dbg_btb = KarrayProbe(self.table)
