# Pieces every pipeline block leans on, whatever stage it belongs to.
#
# block_manager.py is the lifecycle base class: a block collects configuration
# as plain Python, freezes it, and only then becomes a Kathryn module. It models
# the lifecycle and nothing else — how a block takes its config is the block's
# own business. Nothing here names a specific ISA, and BlockManager itself
# imports no Kathryn.

from __future__ import annotations

from .block_manager import BlockManager, BlockStatus
from .hw_util import ceil_log2

__all__ = ["BlockManager", "BlockStatus", "ceil_log2"]
