# Reading the instruction word by the description's rules — the extraction
# half of a matcher.
#
# - `word` is OPAQUE: an int under pytest, a Kathryn signal under
#   elaboration, one meaning both ways — hence `Any`, and no Kathryn import
# - rule parameters are real description types (isa never imports back)
# - decode is the ONE consumer (uop_contract.md §2): nothing downstream
#   carries the raw word

from __future__ import annotations

from typing import Any

from carolyne.isa import InstrFieldMatch, InstrValueMatch, Operand


def extract_field_bits(word: Any, field: InstrFieldMatch) -> Any:
    """Pull the field's bits out of the word.

    - segments land in WRITTEN order, first segment lowest (field_match.py)
    - one segment + sliceable word -> SLICE view: a bare part-select,
      no shift/mask wires in the Verilog
    - else (int word / scrambled field) -> shift-and-OR, kept FULL-WIDTH:
      ints can't slice, Kathryn has no concat, a shifted slice truncates
    - both spellings mean the SAME BITS, held equal here and only here
    """
    if not isinstance(word, int) and len(field.match_idx) == 1:
        start, end = field.match_idx[0]
        return word[end - 1, start]              # inclusive slicing, [hi, lo]

    value, pos = None, 0
    for start, end in field.match_idx:
        segment = (word >> start) & ((1 << (end - start)) - 1)
        if pos:
            segment = segment << pos
        value = segment if value is None else value | segment
        pos  += end - start
    return value


def match_field_bits(word: Any,
                     field: InstrFieldMatch,
                     value: InstrValueMatch) -> Any:
    """True when every segment of the field equals its stated value.

    - one compare per (segment, value) pair, AND-ed
    - sliceable word -> slice compare (a bare part-select, no shift/mask)
    - int word -> shift-and-mask compare, same bits
    """
    hit = None
    for (start, end), want in zip(field.match_idx, value.match_value):
        if isinstance(word, int):
            compare = ((word >> start) & ((1 << (end - start)) - 1)) == want
        else:
            compare = word[end - 1, start] == want
        hit = compare if hit is None else hit & compare
    return hit


def extract_arch_index(word: Any, operand: Operand) -> Any:
    """The architectural register number a slot names: a literal for an
    implicit register (x86 push→ESP), else the decoded field's own bits."""
    if isinstance(operand.index, int):
        return operand.index
    if operand.matcher is None:
        raise ValueError(
            f"operand '{operand.atomic.name}' decodes its index from "
            f"field '{operand.index.name}' but carries no matcher saying "
            f"where that field sits")
    return extract_field_bits(word, operand.matcher)


def extract_imm_value(word: Any, operand: Operand) -> Any:
    # LIMIT — the open extraction gap (isa/field_match.py): naive assembly.
    # - no sign extension, no placement, no implicit zeros
    # - right for contiguous unsigned fields (shamt); WRONG for imm_b/imm_j
    #   and every signed immediate
    # - the real extraction rule swaps in HERE when the contract grows it
    if operand.matcher is None:
        raise ValueError(
            f"immediate operand '{operand.atomic.name}' has no "
            f"matcher — nothing says which bits carry its value")
    return extract_field_bits(word, operand.matcher)
