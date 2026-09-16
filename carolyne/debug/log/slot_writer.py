# THE SLOT TABLE — one simulated cycle is one row of centered cells, the shape
# the C++ engine's SlotWriter prints:
#
#   +---------+-------------------+
#   |  CYCLE  |       FETCH       |
#   +---------+-------------------+
#   |   412   |      RUNNING      |
#   |         |     pc:0x0088     |
#   +---------+-------------------+
#
# A cell holds SEVERAL lines and a row is as tall as its tallest cell; a short
# cell is padded with blank lines, so the columns stay aligned. A line wider
# than its column is CUT with `…` — the C++ let it overflow, which breaks every
# column to its right.
#
# Three sinks take the rows, and they differ only in WHAT THEY KEEP:
#   StreamWriter   every row, one file            short runs and tests
#   WindowWriter   the last N rows, written at close()   the default
#   ChunkedWriter  every row, one file per N rows
# A window renders each row as it arrives and keeps the TEXT, so holding 2500
# cycles costs no handles and no model state.

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Sequence, TextIO

CUT_MARK       = "…"
DEFAULT_WINDOW = 2500
DEFAULT_CHUNK  = 2000


@dataclass(frozen=True)
class Column:
    """One column of the table: what it is called and how wide it prints."""
    name  : str
    width : int

    def __post_init__(self) -> None:
        if self.width < len(CUT_MARK) + 1:
            raise ValueError(f"Column '{self.name}': width {self.width} is too narrow to cut a line into")


class Row:
    """One cycle's cells, one list of lines per column."""

    def __init__(self, column_cnt: int) -> None:
        self.cells : List[List[str]] = [[] for _ in range(column_cnt)]

    def add(self, column_idx: int, line: str) -> None:
        # A newline inside a cell would break the row's own line count.
        self.cells[column_idx].append(line.replace("\n", " "))

    def add_all(self, column_idx: int, lines: Sequence[str]) -> None:
        for line in lines:
            self.add(column_idx, line)

    def height(self) -> int: return max((len(cell) for cell in self.cells), default=0)


# ---- rendering -----------------------------------------------------------------

class SlotTable:
    """The columns, and how a row of them is printed."""

    def __init__(self, columns: Sequence[Column]) -> None:
        if not columns:
            raise ValueError("SlotTable: needs at least one column")
        self.columns = tuple(columns)

    def new_row(self) -> Row: return Row(len(self.columns))

    def index_of(self, name: str) -> int:
        for idx, column in enumerate(self.columns):
            if column.name == name:
                return idx
        raise KeyError(f"SlotTable: no column named {name!r} (have {[c.name for c in self.columns]})")

    def render_rule(self) -> str:
        # A `+` at every column boundary, where the C++ ran the dashes flat: the
        # width is the same and the rule lines up with the separators above it.
        return "+" + "".join("-" * column.width + "+" for column in self.columns) + "\n"

    def render_header(self) -> str:
        row = self.new_row()
        for idx, column in enumerate(self.columns):
            row.add(idx, column.name)
        return self.render_rule() + self.render_row(row)

    def render_row(self, row: Row) -> str:
        """The row's lines, every cell centered in its column, then a rule."""
        out = []
        for line_idx in range(row.height()):
            parts = ["|"]
            for column_idx, column in enumerate(self.columns):
                cell = row.cells[column_idx]
                text = cell[line_idx] if line_idx < len(cell) else ""
                parts.append(center(text, column.width) + "|")
            out.append("".join(parts))
        return ("\n".join(out) + "\n" if out else "") + self.render_rule()


def center(text: str, width: int) -> str:
    """`text` centered in exactly `width` characters, cut with `…` when too long."""
    if len(text) > width:
        text = text[:width - len(CUT_MARK)] + CUT_MARK
    before = (width - len(text) + 1) // 2
    return " " * before + text + " " * (width - len(text) - before)


# ---- sinks ----------------------------------------------------------------------

class RowSink:
    """Where rendered rows go. A sink is opened by its constructor and finished
    by close(), which is the only place a window writes anything."""

    def write(self, cycle: int, row: Row) -> None: raise NotImplementedError
    def close(self)                       -> None: raise NotImplementedError


class StreamWriter(RowSink):
    """Every row, appended to one file as it arrives."""

    def __init__(self, path: str, table: SlotTable) -> None:
        self.table  = table
        self.path   = path
        self.handle : Optional[TextIO] = open_for_table(path)
        self.handle.write(table.render_header())

    def write(self, cycle: int, row: Row) -> None:
        self.handle.write(self.table.render_row(row))

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class WindowWriter(RowSink):
    """The last `window` rows, kept as rendered TEXT and written at close()."""

    def __init__(self, path: str, table: SlotTable, window: int = DEFAULT_WINDOW) -> None:
        if window < 1:
            raise ValueError(f"WindowWriter: window must be >= 1, got {window}")
        self.table  = table
        self.path   = path
        self.window = window
        self.seen   = 0
        self.rows   : Deque[str] = deque(maxlen=window)

    def write(self, cycle: int, row: Row) -> None:
        self.seen += 1
        self.rows.append(self.table.render_row(row))

    def close(self) -> None:
        with open_for_table(self.path) as handle:
            if self.seen > len(self.rows):
                handle.write(f"# the last {len(self.rows)} of {self.seen} cycles\n")
            handle.write(self.table.render_header())
            handle.writelines(self.rows)


class ChunkedWriter(RowSink):
    """Every row, one file of `rows_per_file` per chunk, each with its own header."""

    def __init__(
        self,
        out_dir       : str,
        table         : SlotTable,
        rows_per_file : int = DEFAULT_CHUNK,
        stem          : str = "trace",
    ) -> None:
        if rows_per_file < 1:
            raise ValueError(f"ChunkedWriter: rows_per_file must be >= 1, got {rows_per_file}")
        self.table         = table
        self.out_dir       = out_dir
        self.rows_per_file = rows_per_file
        self.stem          = stem
        self.written       = 0
        self.paths         : List[str]        = []
        self.handle        : Optional[TextIO] = None
        os.makedirs(out_dir, exist_ok=True)

    def write(self, cycle: int, row: Row) -> None:
        if self.written % self.rows_per_file == 0:
            self.roll_file()
        self.handle.write(self.table.render_row(row))
        self.written += 1

    def roll_file(self) -> None:
        """Start the next chunk, header first, so each file opens on its own."""
        if self.handle is not None:
            self.handle.close()
        path = os.path.join(self.out_dir, f"{self.stem}.{len(self.paths):04d}.sl")
        self.paths.append(path)
        self.handle = open_for_table(path)
        self.handle.write(self.table.render_header())

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def open_for_table(path: str) -> TextIO:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return open(path, "w", encoding="utf-8")
