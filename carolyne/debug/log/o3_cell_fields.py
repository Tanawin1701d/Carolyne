# THE FIELD NAMES EACH CELL READS — one small record per log record, holding the
# names o3_cell reaches for.
#
# Built once by o3_cycle from the ISA's own operands; a cell function never
# derives a name, so a record that grows a field is a change here and nowhere
# else. SlotFields is the operand half, and every other record names it.

from __future__ import annotations

from typing import Dict, Optional, Sequence


class SlotFields:
    """One operand slot's field names in one record."""
    def __init__(
        self,
        label  : str,
        active : str = "",
        valid  : str = "",
        pr_idx : str = "",
        ar_idx : str = "",
        data   : str = "",
    ) -> None:
        self.label  = label
        self.active = active
        self.valid  = valid
        self.pr_idx = pr_idx
        self.ar_idx = ar_idx
        self.data   = data


class FetchFields:
    def __init__(
        self,
        valid : str,
        instr : str,
        pc    : str,
    ) -> None:
        self.valid = valid
        self.instr = instr
        self.pc    = pc


class DecodeFields:
    def __init__(
        self,
        valid     : str,
        uop_idx   : str,
        pc        : str,
        rsv_id    : str,
        is_branch : str,
        is_store  : str,
    ) -> None:
        self.valid     = valid
        self.uop_idx   = uop_idx
        self.pc        = pc
        self.rsv_id    = rsv_id
        self.is_branch = is_branch
        self.is_store  = is_store


class DispatchFields:
    def __init__(
        self,
        valid       : str,
        uop_idx     : str,
        rob_des_idx : str,
        is_spec     : str,
        spec_tag    : str,
        dest_pr_idx : Sequence[SlotFields],
    ) -> None:
        self.valid       = valid
        self.uop_idx     = uop_idx
        self.rob_des_idx = rob_des_idx
        self.is_spec     = is_spec
        self.spec_tag    = spec_tag
        self.dest_pr_idx = tuple(dest_pr_idx)


class RsvFields:
    def __init__(
        self,
        valid       : str,
        uop_idx     : str,
        rob_des_idx : str,
        is_spec     : str,
        spec_tag    : str,
        src_slots   : Sequence[SlotFields],
        uop_names   : Dict[int, str],
        pc          : Optional[str] = None,
    ) -> None:
        self.valid       = valid
        self.uop_idx     = uop_idx
        self.rob_des_idx = rob_des_idx
        self.is_spec     = is_spec
        self.spec_tag    = spec_tag
        self.src_slots   = tuple(src_slots)
        self.uop_names   = uop_names
        self.pc          = pc


class RobFields:
    def __init__(
        self,
        wb_fin    : str,
        pc        : str,
        is_branch : str,
        is_store  : str,
        dests     : Sequence[SlotFields],
    ) -> None:
        self.wb_fin    = wb_fin
        self.pc        = pc
        self.is_branch = is_branch
        self.is_store  = is_store
        self.dests     = tuple(dests)


class StBufFields:
    def __init__(
        self,
        busy     : str,
        complete : str,
        is_spec  : str,
        spec_tag : str,
        mem_addr : str,
        data     : str,
    ) -> None:
        self.busy     = busy
        self.complete = complete
        self.is_spec  = is_spec
        self.spec_tag = spec_tag
        self.mem_addr = mem_addr
        self.data     = data
