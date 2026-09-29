# The backend contract: what every synthesis backend takes and gives back, and
# the key a finished bitstream is cached under.
#
#   BoardInfo         one row of a backend's board table
#   BitstreamRequest  what to build: the emitted rtl, its top, its host map, a board, a clock
#   Bitstream         what came out: the .bit and .hwh, and the build's report
#   FpgaBackend       the ABC: boards(), describe(), build()
#
# bitstream_key() is the cache key: the emitted RTL's content digest plus every
# fact the build depends on, so a second run of the same machine finds its
# bitstream and a changed clock or board does not.

from __future__ import annotations

import hashlib
import json
import pathlib
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional, Sequence

from kathryn.sim.rtl import Rtl

from examples.fpga.bridge import HostMap


@dataclass(frozen=True)
class BoardInfo:
    """One board a backend can build for."""

    key               : str          # the name a caller picks it by
    part              : str          # the FPGA part
    board_part        : str          # the vendor board definition, "" when the part alone is stated
    board_connections : str          # extra board connections the project needs, "" when none
    ps_ip             : str          # the processing-system IP, "" for a board with none
    host_base_addr    : int          # where the PS sees the HostBridge window
    gpio_base_addr    : int          # where the PS sees the reset GPIO
    description       : str = ""

    def facts(self) -> dict: return asdict(self)


@dataclass(frozen=True)
class BitstreamRequest:
    """What one bitstream is built from."""

    rtl_dir    : str
    top_module : str
    host_map   : HostMap
    board      : BoardInfo
    clock_mhz  : int
    jobs       : int  = 8
    synth_only : bool = False
    name       : str  = "carolyne"


@dataclass(frozen=True)
class Bitstream:
    """What a build produced; `reused` when the cache already held it."""

    bit_path      : str
    hwh_path      : str
    host_map_path : str
    build_dir     : str
    reused        : bool
    report        : Dict[str, object] = field(default_factory=dict)

    @property
    def timing_met(self) -> Optional[bool]:
        value = self.report.get("timing_met")
        return None if value is None else bool(value)


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
    def build(self, request: BitstreamRequest, build_dir: pathlib.Path,
              log_path: Optional[pathlib.Path] = None) -> Bitstream:
        """Run the tool in `build_dir`; raise RuntimeError with the log's tail on failure."""

    def board(self, key: str) -> BoardInfo:
        boards = self.boards()
        if key not in boards:
            raise ValueError(
                f"backend '{self.name}' knows no board '{key}' — one of {sorted(boards)}")
        return boards[key]


def bitstream_key(rtl: Rtl, backend: FpgaBackend, request: BitstreamRequest) -> str:
    """16 hex digits over the RTL's content and everything the build depends on."""
    digest = rtl.sources_digest()
    facts  = {"backend"   : backend.name,
              "tool"      : backend.describe(),
              "board"     : request.board.facts(),
              "clock_mhz" : request.clock_mhz,
              "addr_bits" : request.host_map.addr_bits,
              "top"       : request.top_module,
              "synth_only": request.synth_only,
              "templates" : [_file_digest(path) for path in backend.template_files()]}
    digest.update(json.dumps(facts, sort_keys=True).encode())
    return digest.hexdigest()[:16]


def _file_digest(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]
