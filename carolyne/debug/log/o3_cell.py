# ONE CELL OF THE SLOT TABLE, formatted. Every function here is PURE: it takes
# values already read off the probes and returns the lines of one cell, so the
# layout can be read and tested without a simulator.
#
# The shapes follow the C++ engine's simStatePrintSlot, with its gating:
#   - a stage that is not running prints its status word and nothing else
#   - an unoccupied entry prints NOTHING at all
#   - register state prints only what CHANGED
#
# A value that did not resolve prints as `--`, never as 0.

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from carolyne.debug.log.o3_cell_fields import (DecodeFields, DispatchFields, FetchFields,
                                               RobFields, RsvFields, SlotFields, StBufFields)

UNSET       = "--"      # a value that did not resolve; never printed as 0
NOT_RENAMED = "-"       # a register the rename table does not cover

# Every status but IDLE — an idle stage holds no entry to print beside it.
STATUS_WITH_DETAIL = ("RUNNING", "HELD", "STALL", "FLUSH", "BUSY", "UNKNOWN")

# ---- what a cell is handed -------------------------------------------------------
# One record as a probe read it. A value is None where the manifest could not reach
# the signal, so a cell reads with `.get`, never `[]`.
ProbeRow = Dict[str, Optional[int]]
# One entry per LANE, in lane order — the position IS the lane number. A lane whose
# `valid` was low is not read at all and carries that one field alone, which is the
# other half of why a cell reads with `.get`.
LaneRows = Sequence[ProbeRow]


# ---- converters ----------------------------------------------------------------

def cvt_val_to_hex(value: Optional[int], digits: int = 8) -> str:
    return UNSET if value is None else f"0x{value:0{digits}x}"


def cvt_val_to_bin(value: Optional[int], width: int) -> str:
    return UNSET if value is None else f"0b{value:0{width}b}"


def cvt_val_to_dec(value: Optional[int]) -> str:
    return UNSET if value is None else str(value)


def cvt_val_to_signed(value: Optional[int], width: int = 32) -> int:
    """An unresolved value answers 0 here, where the text converters answer `--`."""
    if value is None:
        return 0
    return value - (1 << width) if value >= (1 << (width - 1)) else value


def cvt_uop_idx_to_name(table: Dict[int, str], index: Optional[int]) -> str:
    """Falls back to the bare index (`uop7`) when the table names no such µop."""
    if index is None:
        return UNSET
    return table.get(index, f"uop{index}")


# ---- front end -------------------------------------------------------------------

def fetch_lines(
    status    : str,
    next_pc   : Optional[int],
    lane_rows : LaneRows,
    fields    : FetchFields,
) -> List[str]:
    """The status word, where fetch goes NEXT, and the group it is holding.

    - each lane prints its OWN recorded pc beside its instruction word: the pc
      register has already moved on to the next group, so printing it against
      these words would pair an address with an instruction that is not at it
    """
    lines = [status]
    if status not in STATUS_WITH_DETAIL:
        return lines
    lines.append(f"next:{cvt_val_to_hex(next_pc)}")
    for lane, row in enumerate(lane_rows):
        if row.get(fields.valid) == 1:
            lines.append(f"{lane}] {cvt_val_to_hex(row.get(fields.pc))}")
            lines.append(f"   {cvt_val_to_hex(row.get(fields.instr))}")
    return lines


def decode_lines(
    status    : str,
    lane_rows : LaneRows,
    uop_names : Dict[int, str],
    fields    : DecodeFields,
) -> List[str]:
    """The status word, then one lane per decoded µop: what it is and where it goes."""
    lines = [status]
    if status not in STATUS_WITH_DETAIL:
        return lines
    for lane, row in enumerate(lane_rows):
        if row.get(fields.valid) != 1:
            continue
        lines.append(f"{lane}] {cvt_uop_idx_to_name(uop_names, row.get(fields.uop_idx))}"
                     f" pc:{cvt_val_to_hex(row.get(fields.pc))}")
        lines.append(f"   rsv{cvt_val_to_dec(row.get(fields.rsv_id))}"
                     f" br:{cvt_val_to_dec(row.get(fields.is_branch))}"
                     f" st:{cvt_val_to_dec(row.get(fields.is_store))}")
    return lines


def dispatch_lines(
    status         : str,
    ready          : Optional[int],
    lane_rows      : LaneRows,
    uop_names      : Dict[int, str],
    fields         : DispatchFields,
    spec_tag_width : int,
) -> List[str]:
    """The status word and the go bit, then each lane's renamed µop."""
    lines = [f"{status} go:{cvt_val_to_dec(ready)}"]
    if status not in STATUS_WITH_DETAIL:
        return lines
    for lane, row in enumerate(lane_rows):
        if row.get(fields.valid) != 1:
            continue
        lines.append(f"{lane}] {cvt_uop_idx_to_name(uop_names, row.get(fields.uop_idx))}"
                     f" rob:{cvt_val_to_dec(row.get(fields.rob_des_idx))}")
        lines.append(f"   sp:{cvt_val_to_dec(row.get(fields.is_spec))}"
                     f" tg:{cvt_val_to_bin(row.get(fields.spec_tag), spec_tag_width)}")
        for dest in fields.dest_pr_idx:
            if row.get(dest.active) == 1:
                lines.append(f"   {dest.label}->p{cvt_val_to_dec(row.get(dest.pr_idx))}")
    return lines


# ---- the back end ------------------------------------------------------------------

def read_wait_label(row: ProbeRow, slot: SlotFields) -> str:
    """One waiting slot: its name, and the physical register it waits on.

    - which producer has not written back is what a stuck station is always
      asking; a µtemp source carries no pr_idx field, so it names itself alone
    """
    phy = row.get(slot.pr_idx)
    return slot.label if phy is None else f"{slot.label}<-p{phy}"


def rsv_entry_lines(
    idx            : int,
    row            : ProbeRow,
    ready          : bool,
    fields         : RsvFields,
    spec_tag_width : int,
) -> List[str]:
    """One waiting entry, the C++ two-line form; an empty entry prints nothing."""
    if row.get(fields.valid) != 1:
        return []
    head = f"{idx}] {cvt_uop_idx_to_name(fields.uop_names, row.get(fields.uop_idx))}"
    if fields.pc is not None:
        head += f" pc:{cvt_val_to_hex(row.get(fields.pc))}"
    head += f" rob:{cvt_val_to_dec(row.get(fields.rob_des_idx))}"
    lines = [head]
    waits = [read_wait_label(row, slot) for slot in fields.src_slots
             if row.get(slot.active) == 1 and row.get(slot.valid) != 1]
    lines.append("   READY!" if not waits else "   W:" + ",".join(waits))
    if row.get(fields.is_spec) == 1:
        lines.append(f"   sp:1 tg:{cvt_val_to_bin(row.get(fields.spec_tag), spec_tag_width)}")
    return lines


def rob_lines(
    alloc     : Optional[int],
    com       : Optional[int],
    used      : Optional[int],
    committed : Sequence[ProbeRow],
    live      : Sequence[Tuple[int, ProbeRow]],
    fields    : RobFields,
) -> List[str]:
    """The three pointers, the lanes that retired, then the head entries."""
    lines = [f"a:{cvt_val_to_dec(alloc)} c:{cvt_val_to_dec(com)} u:{cvt_val_to_dec(used)}"]
    for row in committed:
        lines.append(f"C{cvt_val_to_dec(row.get('lane'))} {cvt_val_to_hex(row.get(fields.pc))}"
                     f" {rob_dest_text(row, fields)}")
    for idx, row in live:
        lines.append(f"E:{idx}/f:{cvt_val_to_dec(row.get(fields.wb_fin))}"
                     f"/{rob_dest_text(row, fields)}")
    return lines


def rob_dest_text(row: ProbeRow, fields: RobFields) -> str:
    """What this entry retires: its architectural register, or `-`."""
    for dest in fields.dests:
        if row.get(dest.active) == 1:
            return f"r{cvt_val_to_dec(row.get(dest.ar_idx))}<-p{cvt_val_to_dec(row.get(dest.pr_idx))}"
    return "r-"


def st_buf_entry_lines(
    idx            : int,
    row            : ProbeRow,
    fields         : StBufFields,
    spec_tag_width : int,
) -> List[str]:
    """One buffered store, the C++ two-line form; an empty slot prints nothing."""
    if row.get(fields.busy) != 1:
        return []
    return [f"[{idx} cpt:{cvt_val_to_dec(row.get(fields.complete))}"
            f" sp:{cvt_val_to_dec(row.get(fields.is_spec))}"
            f" tg:{cvt_val_to_bin(row.get(fields.spec_tag), spec_tag_width)}",
            f"  @{cvt_val_to_dec(row.get(fields.mem_addr))} = {cvt_val_to_hex(row.get(fields.data))}"]


def mpft_lines(rows: Sequence[ProbeRow], fix_tag_field: str, width: int) -> List[str]:
    """One line per speculation tag: the mask a squash under it would kill."""
    return [f"{idx} {cvt_val_to_bin(row.get(fix_tag_field), width)}"
            for idx, row in enumerate(rows) if row.get(fix_tag_field)]


# ---- register state ----------------------------------------------------------------

def reg_change_lines(changes: Sequence[Tuple[int, str]], per_line: int = 8) -> List[str]:
    """Changed registers only, `idx:value` cells, `per_line` to a line."""
    lines, cells = [], []
    for index, text in changes:
        cells.append(f"{index}:{text}")
        if len(cells) == per_line:
            lines.append(" ".join(cells))
            cells = []
    if cells:
        lines.append(" ".join(cells))
    return lines


def rename_text(row: ProbeRow, renamed_field: str, prf_idx_field: str) -> str:
    """What a rename-table row says: the physical register, or `-` when not renamed."""
    if row.get(renamed_field) != 1:
        return NOT_RENAMED
    return f"p{cvt_val_to_dec(row.get(prf_idx_field))}"
