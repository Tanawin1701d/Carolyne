# The backend contract's records: what every synthesis backend takes and gives
# back, and the key a finished bitstream is cached under. The backend class
# itself (FpgaBackend, the ABC) is in fpga_backend.py.
#
#   BoardInfo         one row of a backend's board table
#   BitstreamRequest  what to build: the emitted rtl, its top, its host map, a board, a clock
#   Bitstream         what came out: the .bit and .hwh, and the build's report
#
# bitstream_key() is the cache key: the emitted RTL's content digest plus every
# fact the build depends on, so a second run of the same machine finds its
# bitstream and a changed clock or board does not.

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Dict, Optional

from kathryn.sim.rtl import Rtl

from examples.fpga.bridge import HostMap

if TYPE_CHECKING:                       # a hint only: fpga_backend.py imports this file
    from examples.fpga.backend.fpga_backend import FpgaBackend


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
