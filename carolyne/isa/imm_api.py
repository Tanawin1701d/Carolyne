# ImmApi — what an immediate's EXTRACTION body reaches the engine through:
# the rule that turns the fetched instruction word into the value a µop
# record carries (uop_contract.md §1.3, the extraction half of a matcher).
#
# An operand states its rule as a callable on `Operand.imm_extract`. The body
# WRITES its result rather than returning one — the engine hands it a wire of
# the immediate's width, zero everywhere nothing is placed:
#
#     def imm_i(word, api):
#         api.place(word, 31, 20, at=0)
#         api.sign_extend(from_bit=11)
#
# - `word` is the fetched instruction, OPAQUE — an int under pytest, a
#   Kathryn signal under elaboration, one meaning both ways
# - a matcher says WHICH bits carry the immediate and is what tells one from
#   a linking µtemp; this says what those bits MEAN
#
# Placement is a SLICE WRITE, not shift-and-mask: `out[at+n-1, at] *=
# word[hi, lo]` is a bare part-select on both sides, so a segment costs
# WIRING and no gates. Sign extension fans the sign bit into the bits above
# it. Both spellings fall back to integer arithmetic when `word` is an int,
# which is what keeps a rule testable with no Kathryn and no engine.

from __future__ import annotations

from typing import Any, Optional

from kathryn.combinational import mux


class ImmApi:
    """The engine half of an immediate's extraction body.

    Built per extraction by whoever calls the rule (decode), carrying the
    width the result must fit — the SELECTED target's, so a body never
    restates a number the description already holds.

    `out` is the destination wire; omitted (an int `word`, under pytest) the
    api accumulates an int instead and `value` reads it back.
    """

    def __init__(self,
                 width : int,
                 where : str = "imm_extract",
                 out   : Optional[Any] = None) -> None:
        self.width = width
        self.where = where
        self.out   = out
        self._acc  = 0          # int-mode accumulator, unused in hardware

    @property
    def is_hw(self) -> bool:
        return self.out is not None

    @property
    def value(self) -> Any:
        """What the rule built: the driven wire, or the assembled int."""
        return self.out if self.is_hw else self._acc

    # --- assembly (concrete) --------------------------------------------------
    def place(self, word: Any, hi: int, lo: int, at: int = 0) -> None:
        """Drive the result's bits [at+n-1 : at] from the word's [hi : lo].

        - a part-select on both sides: no shift, no mask, no gates
        - bits nothing places stay ZERO (a branch target's implicit bit 0),
          which is the wire's own undriven fallback
        - each call drives a DISJOINT slice, so two placements never contend
        """
        self._check_place(hi, lo, at)
        seg_width = hi - lo + 1
        if self.is_hw:
            self.out[at + seg_width - 1, at] *= word[hi, lo]
        else:
            self._acc |= ((word >> lo) & ((1 << seg_width) - 1)) << at

    def sign_extend(self, from_bit: int) -> None:
        """Fill the result above `from_bit` with that bit, treating it as sign.

        - a mux between all-ones and all-zeros on the sign bit: the emitted
          logic is that one bit fanned out, where `(v ^ m) - m` would cost a
          full-width xor AND a full-width subtract
        - call it AFTER the placements: it reads the sign bit back off the
          result, so the bit must already be driven
        """
        if not isinstance(from_bit, int) or isinstance(from_bit, bool):
            raise TypeError(f"{self.where}: sign_extend() takes an int bit position")
        if not (0 <= from_bit < self.width):
            raise ValueError(
                f"{self.where}: sign_extend() wants 0 <= from_bit < {self.width}, "
                f"got {from_bit}")
        top = self.width - 1
        if from_bit == top:
            return                          # nothing above the sign to fill
        if self.is_hw:
            fill_width = top - from_bit
            self.out[top, from_bit + 1] *= mux(self.out[from_bit, from_bit],
                                               (1 << fill_width) - 1, 0,
                                               width=fill_width)
        else:
            m = 1 << from_bit
            self._acc = (self._acc ^ m) - m

    # --- validation -----------------------------------------------------------
    def _check_place(self, hi: int, lo: int, at: int) -> None:
        for name, pos in (("hi", hi), ("lo", lo), ("at", at)):
            if not isinstance(pos, int) or isinstance(pos, bool):
                raise TypeError(
                    f"{self.where}: place() takes int bit positions, "
                    f"{name}={pos!r}")
        if hi < lo or lo < 0:
            raise ValueError(
                f"{self.where}: place() wants hi >= lo >= 0, got hi={hi}, lo={lo}")
        if at < 0:
            raise ValueError(f"{self.where}: place() wants at >= 0, got {at}")
        if at + (hi - lo + 1) > self.width:
            raise ValueError(
                f"{self.where}: placing {hi - lo + 1} bits at {at} runs past the "
                f"{self.width}-bit immediate")
