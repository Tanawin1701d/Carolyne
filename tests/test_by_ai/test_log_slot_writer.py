# The slot table: how a cell is centered, how a row of uneven cells prints,
# and what each of the three sinks keeps.

from __future__ import annotations

import pytest

from carolyne.debug.log.slot_writer import (ChunkedWriter, Column, SlotTable, StreamWriter, WindowWriter, center)


def small_table() -> SlotTable:
    return SlotTable([Column("CYCLE", 9), Column("FETCH", 19)])


# ---- rendering ------------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("412",        "   412   "),     # centered, the odd space going before
    ("",           "         "),
    ("abcdefghi",  "abcdefghi"),     # exactly the width
    ("abcdefghij", "abcdefgh…"),     # one over: cut, and still exactly as wide
])
def test_a_cell_is_exactly_its_column_wide(text, want):
    assert center(text, 9) == want and len(want) == 9


def test_a_line_too_long_is_cut_with_a_mark():
    assert center("a very long line indeed", 9) == "a very l…"


def test_a_short_cell_is_padded_so_the_columns_stay_aligned():
    table = small_table()
    row   = table.new_row()
    row.add(0, "412")
    row.add_all(1, ["RUNNING", "pc:0x88"])
    lines = table.render_row(row).splitlines()
    assert len(lines) == 3                                  # two cell lines and the rule
    assert lines[0] == "|   412   |      RUNNING      |"
    assert lines[1] == "|         |      pc:0x88      |"    # the short cell is blank here
    assert lines[2] == "+---------+-------------------+"


def test_the_header_names_the_columns_between_rules():
    lines = small_table().render_header().splitlines()
    assert lines[0] == lines[2] == "+---------+-------------------+"
    assert lines[1] == "|  CYCLE  |       FETCH       |"


def test_the_rule_is_as_wide_as_a_row():
    table = small_table()
    row   = table.new_row()
    row.add(0, "1")
    assert len(table.render_rule().rstrip("\n")) == len(table.render_row(row).splitlines()[0])


def test_a_newline_inside_a_cell_cannot_break_the_row():
    table = small_table()
    row   = table.new_row()
    row.add(0, "a\nb")
    assert row.cells[0] == ["a b"]


def test_a_column_too_narrow_to_cut_is_refused():
    with pytest.raises(ValueError, match="too narrow"):
        Column("X", 1)


# ---- the sinks -------------------------------------------------------------------

def rows_into(sink, table, count: int) -> None:
    for cycle in range(count):
        row = table.new_row()
        row.add(0, str(cycle))
        sink.write(cycle, row)
    sink.close()


def test_a_stream_writes_every_row_as_it_arrives(tmp_path):
    table = small_table()
    path  = tmp_path / "trace.sl"
    sink  = StreamWriter(str(path), table)
    rows_into(sink, table, 5)
    text = path.read_text()
    assert text.count("CYCLE") == 1                      # one header, at the top
    assert all(f"|    {n}    |" in text for n in range(5))


def test_a_window_keeps_the_last_rows_and_writes_only_at_close(tmp_path):
    table = small_table()
    path  = tmp_path / "trace.sl"
    sink  = WindowWriter(str(path), table, window=3)
    for cycle in range(10):
        row = table.new_row()
        row.add(0, str(cycle))
        sink.write(cycle, row)
    assert not path.exists()                              # nothing is written until close
    sink.close()
    text = path.read_text()
    assert "the last 3 of 10 cycles" in text
    assert "|    9    |" in text and "|    7    |" in text
    assert "|    6    |" not in text


def test_a_window_shorter_than_its_limit_says_nothing_about_dropping(tmp_path):
    table = small_table()
    path  = tmp_path / "trace.sl"
    sink  = WindowWriter(str(path), table, window=100)
    rows_into(sink, table, 4)
    assert "the last" not in path.read_text()


def test_chunks_roll_at_the_row_count_and_each_file_opens_on_its_own(tmp_path):
    table = small_table()
    sink  = ChunkedWriter(str(tmp_path), table, rows_per_file=3)
    rows_into(sink, table, 7)
    assert [p.name for p in sorted(tmp_path.glob("trace.*.sl"))] == [
        "trace.0000.sl", "trace.0001.sl", "trace.0002.sl"]
    first = (tmp_path / "trace.0000.sl").read_text()
    last  = (tmp_path / "trace.0002.sl").read_text()
    assert first.count("CYCLE") == 1 and last.count("CYCLE") == 1     # a header per file
    assert "|    6    |" in last and "|    0    |" in first


def test_a_window_of_zero_is_refused():
    with pytest.raises(ValueError, match="window must be"):
        WindowWriter("x", small_table(), window=0)
