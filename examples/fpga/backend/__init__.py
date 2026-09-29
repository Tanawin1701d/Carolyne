# The synthesis backends, behind one registry: a caller names a backend and
# gets its class; a new tool is a new sub-package and one row in BACKENDS.
#
#   base.py       the contract (FpgaBackend, BoardInfo, BitstreamRequest, Bitstream) and the cache key
#   template.py   fill_template: token and marker substitution, backend-neutral
#   vivado/       AMD Vivado: a block design around the emitted top, to a bitstream + hwh

from __future__ import annotations

from typing import Dict, Type

from .base     import Bitstream, BitstreamRequest, BoardInfo, FpgaBackend, bitstream_key
from .template import fill_template, fill_text
from .vivado   import VivadoBackend

BACKENDS: Dict[str, Type[FpgaBackend]] = {"vivado": VivadoBackend}


def get_backend(name: str) -> FpgaBackend:
    """A fresh backend instance by name, case-insensitively."""
    key = name.lower()
    if key not in BACKENDS:
        raise ValueError(f"no FPGA backend named '{name}' — one of {sorted(BACKENDS)}")
    return BACKENDS[key]()


__all__ = ["FpgaBackend", "BoardInfo", "BitstreamRequest", "Bitstream", "bitstream_key",
           "fill_template", "fill_text", "BACKENDS", "get_backend", "VivadoBackend"]
