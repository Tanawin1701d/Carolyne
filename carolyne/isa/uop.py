# Uop — one µop template of a cracked instruction (uop_contract.md §1.4/§2):
# which operation runs and the operand slots the generated hardware fills at
# runtime. Like every ISA-layer type this is TEMPLATE only — srcs/dests are
# index *rules* (Operand), imm is an extraction rule or a cracker-baked
# constant, never a runtime value.
#
# Decisions (2026-08-13):
# - Operand counts are capped at the µop RECORD's shape (§2: src[0..2],
#   dest[0..1]) so a cracker cannot describe a µop the hardware plane
#   cannot carry.
# - `imm` is deliberately NOT an Operand (§2): FieldRef = extracted encoding
#   field; int = constant the cracker bakes in (x86 push adjusts ESP by -4).
# - `op` is a SINGLE concrete Op, so every Uop is fully resolved. An
#   instruction family sharing one shape (RISC-V R-type) is a plain factory
#   function in the per-ISA package; the encoding-table row — which exists
#   per instruction anyway, for the bit pattern — passes the op in. A
#   multi-op `ops` field was tried and reverted: the §2 record carries
#   exactly one `kind`, so a family is an *unbound* template that forces a
#   resolved/unresolved distinction on every consumer downstream, plus a
#   marker for which µop varies in a multi-µop crack. Python-level
#   construction is the templating mechanism here, same as an Intermediate
#   instance being the link between µops.
# - No first/last bound here — that is a property of a template's position
#   in its cracker sequence, stamped by the sequence type (next step).
# - mem (size/sign) and br (cond-kind) sub-fields are deferred until the FU
#   semantics that consume them land.
#
# Decisions (2026-08-14):
# - `op` is an `Op` object (op.py), not a string. A bare string is rejected
#   with TypeError instead of being looked up in a unit: the description
#   layer should hold the catalog object, and `unit.op("ADD")` is the one
#   sanctioned way to turn text (an encoding-table row) into one.
# - The template carries NO unit. A µop names only what it does; which
#   ExecUnit executes it is a machine-configuration question (how many ALUs,
#   which unit claims which op), answered by the unit set at elaboration —
#   ExecUnit.ops is the kind→FU map, read the other way round. Consequence:
#   a wrong (unit, op) pairing can no longer be caught here, and an op listed
#   by several units is a routing choice the elaborator makes, not an error.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union

from .field_match import InstrFieldMatch, InstrValueMatch, check_matcher_pair
from .op import Op
from .operand import FieldRef, Operand

ImmRule = Union[int, FieldRef]

# Hardware-plane record shape, uop_contract.md §2.
MAX_SRCS  = 3       # 3rd source: store data / old-flags read
MAX_DESTS = 2       # 2nd dest: flags write (x86), link reg


@dataclass(frozen=True)
class Uop:

    op      : Op
    srcs    : Tuple[Operand, ...] = ()
    dests   : Tuple[Operand, ...] = ()
    matcher_field : Optional[InstrFieldMatch] = None  # which bits pick this template
    matcher_value : Optional[InstrValueMatch] = None  # what they must equal, per segment

    def __post_init__(self) -> None:
        if not isinstance(self.op, Op):
            raise TypeError(
                f"Uop op must be an Op, got {type(self.op).__name__} "
                f"(name it from the catalog, or <unit>.op(<name>))")
        object.__setattr__(self, "srcs",  tuple(self.srcs))    # accept any sequence
        object.__setattr__(self, "dests", tuple(self.dests))
        for role, operands, limit in (("src",  self.srcs,  MAX_SRCS),
                                      ("dest", self.dests, MAX_DESTS)):
            if len(operands) > limit:
                raise ValueError(
                    f"Uop '{self.op}': {len(operands)} {role} operands, "
                    f"record carries at most {limit} (uop_contract.md §2)")
            for operand in operands:
                if not isinstance(operand, Operand):
                    raise TypeError(
                        f"Uop '{self.op}': {role} operands must be Operand, "
                        f"got {type(operand).__name__}")
        check_matcher_pair(self.matcher_field, self.matcher_value,
                           where=f"Uop '{self.op}'")