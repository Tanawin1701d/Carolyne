# Helpers BOTH planes may reach. Nothing here imports Kathryn, imports
# `isa`/`uarch`, or names an ISA — that emptiness is the whole point: the
# elaboration plane may not import the hardware plane (CLAUDE.md §3), so a
# fact both of them ask (is this a power of two?) has nowhere else to live.
#
# `uarch/common/` stays where uarch-only arithmetic lives (ceil_log2, the word
# readers). A helper earns a place HERE only when `isa/` asks it too.

from __future__ import annotations

from .bit_checking import is_power_of_two

__all__ = ["is_power_of_two"]
