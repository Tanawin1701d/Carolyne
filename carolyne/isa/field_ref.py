# FieldRef — a *rule*, not a value: "the register index arrives at runtime
# from the encoding field of this name" (rd/rs1/modrm_reg/...). The ISA layer
# is pure template; elaboration turns a FieldRef into wiring from the
# generated decoder's field extractor into the rename read/write port.
#
# A FieldRef is only a name here. Which bits the field occupies — and whether
# the name exists at all — is defined by the encoding table and checked when
# a cracker is bound to an encoding (that layer lands later). Equality is by
# name: within one instruction template, "rd" is "rd".

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldRef:
    name : str          # encoding field name, e.g. "rd", "rs1", "modrm_reg"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("FieldRef needs a non-empty field name")
