# THE CONSOLE — what the program printed, in the shape the C++ ResultWriter
# wrote: the cycle count, a banner, then the bytes.
#
#   2041
#   ----- output -----
#   hello from carolyne
#
# A program reaches it by storing to an I/O word (events.py names them), so
# nothing here knows about memory: it takes characters and integers.

from __future__ import annotations

import os
from typing import List

BANNER = "----- output -----"


class ConsoleCapture:
    """The bytes a program printed, in order."""

    def __init__(self) -> None:
        self.parts : List[str] = []

    def put_char(self, value: int) -> None:
        """One character, as the program's byte value."""
        self.parts.append(chr(value & 0xFF))

    def put_int(self, value: int, width: int = 32, signed: bool = True) -> None:
        """One integer in decimal, read back from the word the program stored."""
        if signed and value >= (1 << (width - 1)):
            value -= 1 << width
        self.parts.append(str(value))

    def put_text(self, text: str) -> None:
        self.parts.append(text)

    @property
    def text(self) -> str: return "".join(self.parts)

    def render(self, cycles: int) -> str:
        return f"{cycles}\n{BANNER}\n{self.text}"

    def write(self, path: str, cycles: int) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.render(cycles))
