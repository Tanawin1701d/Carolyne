# Pieces every pipeline block leans on, whatever stage it belongs to.
#
# What this package exports imports NO Kathryn, so the arithmetic every block
# does at elaboration time is testable with no arena and no reset(). Modules
# here that do build hardware are imported by module path instead of being
# re-exported (karray_util).
#
# Nothing here names a specific ISA.

from __future__ import annotations

from .hw_util import ceil_log2
from .word_util import (extract_arch_index, extract_field_bits,
                        extract_imm_value, match_field_bits)

__all__ = ["ceil_log2",
           "extract_arch_index", "extract_field_bits", "extract_imm_value",
           "match_field_bits"]
