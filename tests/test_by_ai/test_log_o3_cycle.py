# The O3 cell formatters and the change tracker: the gating rules the C++ slot
# printer follows — an unoccupied entry prints nothing, a stage that is not
# running prints its status alone, register state prints only what changed.

from __future__ import annotations

from carolyne.debug.log import o3_cell        as CELL
from carolyne.debug.log import o3_cell_fields as FIELDS
from carolyne.debug.log.o3_cycle import O3_COLUMNS, RegChangeTracker

TAG_BITS = 5


def rsv_fields(with_pc: bool = True) -> FIELDS.RsvFields:
    slots = [FIELDS.SlotFields("src_1", active="active_src_1", valid="valid_src_1",
                               pr_idx="pr_idx_src_1"),
             FIELDS.SlotFields("src_2", active="active_src_2", valid="valid_src_2")]
    return FIELDS.RsvFields(valid="valid", uop_idx="uop_idx", rob_des_idx="rob_des_idx",
                            is_spec="is_spec", spec_tag="spec_tag", src_slots=slots,
                            uop_names={2: "JAL"}, pc="pc" if with_pc else None)


def entry(**over):
    row = {"valid": 1, "uop_idx": 2, "pc": 0x88, "rob_des_idx": 5, "is_spec": 0, "spec_tag": 0,
           "active_src_1": 1, "valid_src_1": 1, "pr_idx_src_1": 46,
           "active_src_2": 0, "valid_src_2": 0}
    row.update(over)
    return row


# ---- converters ------------------------------------------------------------------

def test_a_value_that_did_not_resolve_prints_as_unset_not_zero():
    assert CELL.cvt_val_to_hex(None) == CELL.UNSET and CELL.cvt_val_to_dec(None) == CELL.UNSET
    assert CELL.cvt_val_to_bin(None, 4) == CELL.UNSET
    assert CELL.cvt_val_to_hex(0x88) == "0x00000088" and CELL.cvt_val_to_bin(2, 4) == "0b0010"


def test_a_word_reads_back_signed():
    assert CELL.cvt_val_to_signed(0xFFFFFFFF) == -1
    assert CELL.cvt_val_to_signed(5)          == 5
    assert CELL.cvt_val_to_signed(None)       == 0


def test_an_unknown_uop_index_still_prints_something_traceable():
    assert CELL.cvt_uop_idx_to_name({2: "JAL"}, 2) == "JAL"
    assert CELL.cvt_uop_idx_to_name({2: "JAL"}, 9) == "uop9"
    assert CELL.cvt_uop_idx_to_name({}, None) == CELL.UNSET


# ---- the gating rules ---------------------------------------------------------------

def test_an_unoccupied_station_entry_prints_nothing():
    assert CELL.rsv_entry_lines(3, entry(valid=0), True, rsv_fields(), TAG_BITS) == []


def test_a_ready_entry_prints_the_two_line_form():
    lines = CELL.rsv_entry_lines(3, entry(), True, rsv_fields(), TAG_BITS)
    assert lines == ["3] JAL pc:0x00000088 rob:5", "   READY!"]


def test_an_entry_waiting_on_a_source_names_that_source_and_its_register():
    """Which producer has not written back is what a stuck station is asking."""
    lines = CELL.rsv_entry_lines(3, entry(valid_src_1=0), True, rsv_fields(), TAG_BITS)
    assert lines[1] == "   W:src_1<-p46"


def test_a_slot_with_no_physical_register_field_names_itself_alone():
    """A µtemp source carries no pr_idx: the cell must not print 'pNone'."""
    waiting = entry(active_src_2=1, valid_src_2=0)
    lines   = CELL.rsv_entry_lines(3, waiting, True, rsv_fields(), TAG_BITS)
    assert lines[1] == "   W:src_2"


def test_a_slot_the_uop_does_not_fill_is_not_waited_on():
    # active_src_2 is 0, so its unset valid bit must not read as "waiting".
    lines = CELL.rsv_entry_lines(3, entry(), True, rsv_fields(), TAG_BITS)
    assert "src_2" not in "".join(lines)


def test_a_speculating_entry_shows_its_tag():
    lines = CELL.rsv_entry_lines(3, entry(is_spec=1, spec_tag=2), True, rsv_fields(), TAG_BITS)
    assert lines[2] == "   sp:1 tg:0b00010"


def test_a_station_with_no_pc_in_its_entries_prints_none():
    lines = CELL.rsv_entry_lines(3, entry(), True, rsv_fields(with_pc=False), TAG_BITS)
    assert lines[0] == "3] JAL rob:5"


def test_a_stage_that_is_not_running_prints_its_word_alone():
    fields = FIELDS.FetchFields("valid", "instr", "pc")
    assert CELL.fetch_lines("IDLE", 0x88, [{"valid": 1, "instr": 9}], fields) == ["IDLE"]


def test_a_running_fetch_prints_only_the_lanes_the_memory_answered():
    fields = FIELDS.FetchFields("valid", "instr", "pc")
    rows   = [{"valid": 1, "instr": 0x93, "pc": 0x80}, {"valid": 0}]
    # the pc register has moved on, so a lane prints its OWN recorded address
    assert CELL.fetch_lines("RUNNING", 0x88, rows, fields) == [
        "RUNNING", "next:0x00000088", "0] 0x00000080", "   0x00000093"]


def test_an_empty_store_buffer_slot_prints_nothing():
    fields = FIELDS.StBufFields("busy", "complete", "is_spec", "spec_tag", "mem_addr", "data")
    assert CELL.st_buf_entry_lines(2, {"busy": 0}, fields, TAG_BITS) == []
    row = {"busy": 1, "complete": 1, "is_spec": 0, "spec_tag": 0, "mem_addr": 1020, "data": 0x68}
    assert CELL.st_buf_entry_lines(2, row, fields, TAG_BITS) == [
        "[2 cpt:1 sp:0 tg:0b00000", "  @1020 = 0x00000068"]


def test_the_mpft_prints_only_the_tags_that_would_kill_something():
    rows = [{"fix_tag": 0}, {"fix_tag": 0b00110}, {"fix_tag": 0}]
    assert CELL.mpft_lines(rows, "fix_tag", TAG_BITS) == ["1 0b00110"]


# ---- the reorder buffer ----------------------------------------------------------------

def rob_fields() -> FIELDS.RobFields:
    dest = FIELDS.SlotFields("dest_1", active="active_dest_1",
                             pr_idx="pr_idx_dest_1", ar_idx="ar_idx_dest_1")
    return FIELDS.RobFields("wb_fin", "pc", "is_branch", "is_store", [dest])


def test_a_commit_line_names_the_register_it_retired():
    committed = [{"lane": 0, "pc": 0x88, "active_dest_1": 1,
                  "ar_idx_dest_1": 1, "pr_idx_dest_1": 12}]
    lines = CELL.rob_lines(7, 5, 2, committed, [], rob_fields())
    assert lines == ["a:7 c:5 u:2", "C0 0x00000088 r1<-p12"]


def test_an_entry_writing_no_register_says_so():
    live  = [(5, {"wb_fin": 0, "active_dest_1": 0})]
    lines = CELL.rob_lines(7, 5, 2, [], live, rob_fields())
    assert lines[1] == "E:5/f:0/r-"


# ---- register state -------------------------------------------------------------------

def test_change_lines_wrap_at_the_line_width():
    changes = [(idx, f"0x{idx:02x}") for idx in range(5)]
    assert CELL.reg_change_lines(changes, per_line=2) == [
        "0:0x00 1:0x01", "2:0x02 3:0x03", "4:0x04"]


def test_an_unrenamed_register_reads_as_a_dash():
    assert CELL.rename_text({"renamed": 0, "prf_idx": 7}, "renamed", "prf_idx") == CELL.NOT_RENAMED
    assert CELL.rename_text({"renamed": 1, "prf_idx": 7}, "renamed", "prf_idx") == "p7"


def test_the_tracker_reports_a_row_once_and_then_stays_quiet():
    tracker = RegChangeTracker()
    assert tracker.diff(["a", "b"]) == [(0, "a"), (1, "b")]     # the first cycle is all new
    assert tracker.diff(["a", "b"]) == []
    assert tracker.diff(["a", "c"]) == [(1, "c")]


# ---- the table --------------------------------------------------------------------------

def test_the_cycle_column_comes_first_and_every_column_is_named_once():
    names = [column.name for column in O3_COLUMNS]
    assert names[0] == "CYCLE/MPFT" and len(set(names)) == len(names)
