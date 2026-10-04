# FpgaBackend — the ABC every synthesis backend implements: one tool, driven
# from an emitted machine to a bitstream. The records it takes and returns
# (BoardInfo, BitstreamRequest, Bitstream) are in base.py.
#
# A new tool is a subclass in its own sub-package (vivado/ is the one today)
# and one row in backend/__init__.py's BACKENDS.

from __future__ import annotations

import pathlib
from abc import ABC, abstractmethod
from typing import Dict, Optional, Sequence

from examples.fpga.backend.base import Bitstream, BitstreamRequest, BoardInfo


class FpgaBackend(ABC):
    """One synthesis tool, driven to a bitstream."""

    name : str = ""

    @abstractmethod
    def boards(self) -> Dict[str, BoardInfo]:
        """The boards this backend knows, by key."""

    @abstractmethod
    def describe(self) -> str:
        """One line naming the tool and its version — part of the cache key."""

    @abstractmethod
    def template_files(self) -> Sequence[pathlib.Path]:
        """The template files a build is generated from — part of the cache key."""

    @abstractmethod
    def build(self, request  : BitstreamRequest,
                    build_dir: pathlib.Path,
                    log_path : Optional[pathlib.Path] = None) -> Bitstream:
        """Run the tool in `build_dir`; raise RuntimeError with the log's tail on failure."""

    def board(self, key: str) -> BoardInfo:
        boards = self.boards()
        if key not in boards:
            raise ValueError(
                f"backend '{self.name}' knows no board '{key}' — one of {sorted(boards)}")
        return boards[key]
