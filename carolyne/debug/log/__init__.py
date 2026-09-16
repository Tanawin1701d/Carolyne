# carolyne.debug.log — turning a running simulation into something readable.
#
#   slot_writer.py     the table: centered cells, one row per cycle, and the
#                      three sinks (every row / the last N / one file per N)
#   console.py         what the program printed
#   events.py          the few things per cycle worth naming, and when to stop
#   o3_cell.py         pure formatters: values in, the lines of one cell out
#   o3_cell_fields.py  the field names those formatters read, one record each
#   o3_cycle.py        the O3 core's handles and the row it makes each cycle
#
# stdlib only, except that o3_cycle reads the machine's own field-name
# vocabulary (carolyne.uarch.o3). Nothing here imports `examples`.

from __future__ import annotations

from .console     import BANNER, ConsoleCapture
from .events      import (COMMIT, MEM_WRITE, MMIO, REDIRECT, STOP_EXIT, STOP_IDLE, STOP_MAX_CYCLES, CycleEvent,
                          EventsWriter, MmioDoors, StopWatch, apply_console, exit_code_of, read_commit_events,
                          read_redirect_event, read_store_event)
from .slot_writer import (DEFAULT_CHUNK, DEFAULT_WINDOW, ChunkedWriter, Column, Row, RowSink, SlotTable,
                          StreamWriter, WindowWriter, center)

__all__ = ["Column", "Row", "SlotTable", "RowSink", "StreamWriter", "WindowWriter",
           "ChunkedWriter", "center", "DEFAULT_WINDOW", "DEFAULT_CHUNK",
           "ConsoleCapture", "BANNER",
           "CycleEvent", "MmioDoors", "StopWatch", "EventsWriter",
           "read_store_event", "read_commit_events", "read_redirect_event",
           "apply_console", "exit_code_of",
           "MMIO", "MEM_WRITE", "COMMIT", "REDIRECT",
           "STOP_EXIT", "STOP_IDLE", "STOP_MAX_CYCLES"]
