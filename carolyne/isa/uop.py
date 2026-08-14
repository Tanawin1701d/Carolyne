# Uop — one µop template of a cracked instruction (uop_contract.md §1.4/§2):
# which execution unit runs it, which operation, and the operand slots the
# generated hardware fills at runtime. Like every ISA-layer type this is
# TEMPLATE only — srcs/dests are index *rules* (Operand), imm is an
# extraction rule or a cracker-baked constant, never a runtime value.
#
# Decisions (2026-08-13):
# - The unit rides in the template explicitly (unit + op string) instead of
#   being implied by a global kind→unit map: routing is visible in the
#   description and custom FUs need no registry. `op` is validated against
#   `unit.ops` here so a typo fails at construction, not deep in elaboration.
# - Operand counts are capped at the µop RECORD's shape (§2: src[0..2],
#   dest[0..1]) so a cracker cannot describe a µop the hardware plane
#   cannot carry.
# - `imm` is deliberately NOT an Operand (§2): FieldRef = extracted encoding
#   field; int = constant the cracker bakes in (x86 push adjusts ESP by -4).
# - `op` is a SINGLE concrete string, so every Uop is fully resolved. An
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

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union

from .exec_unit import ExecUnit
from .mop import InstrFieldMatch
from .operand import FieldRef, Operand

ImmRule = Union[int, FieldRef]

# Hardware-plane record shape, uop_contract.md §2.
MAX_SRCS  = 3       # 3rd source: store data / old-flags read
MAX_DESTS = 2       # 2nd dest: flags write (x86), link reg


@dataclass(frozen=True)
class Uop:

    unit    : ExecUnit
    op      : str
    srcs    : Tuple[Operand, ...] = ()
    dests   : Tuple[Operand, ...] = ()
    imm     : Optional[ImmRule]   = None
    matcher: Tuple[InstrFieldMatch, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.unit, ExecUnit):
            raise TypeError(f"Uop unit must be an ExecUnit, got {type(self.unit).__name__}")
        if self.op not in self.unit.ops:
            raise ValueError(
                f"Uop op '{self.op}' is not an op of unit '{self.unit.name}' "
                f"(has: {', '.join(sorted(self.unit.ops))})")
        object.__setattr__(self, "srcs",  tuple(self.srcs))    # accept any sequence
        object.__setattr__(self, "dests", tuple(self.dests))
        for role, operands, limit in (("src",  self.srcs,  MAX_SRCS),
                                      ("dest", self.dests, MAX_DESTS)):
            if len(operands) > limit:
                raise ValueError(
                    f"Uop '{self.unit.name}.{self.op}': {len(operands)} {role} operands, "
                    f"record carries at most {limit} (uop_contract.md §2)")
            for operand in operands:
                if not isinstance(operand, Operand):
                    raise TypeError(
                        f"Uop '{self.unit.name}.{self.op}': {role} operands must be Operand, "
                        f"got {type(operand).__name__}")
        if self.imm is not None and not isinstance(self.imm, (int, FieldRef)):
            raise TypeError(
                f"Uop '{self.unit.name}.{self.op}': imm must be an int or FieldRef, "
                f"got {type(self.imm).__name__}")
