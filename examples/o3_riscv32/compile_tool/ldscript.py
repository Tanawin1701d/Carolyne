# The linker script, filled in from the MemoryLayout.
#
# The script itself is template/link.ld.in, not a string in here: it is a
# linker script, so it should be readable and editable as one. render.py says
# why the markers are @NAME@ and not {name}.
#
# THE SPLIT THAT MATTERS is inside the template: .text goes to the instruction
# memory and everything else to the data memory, because the two memories are
# separate hardware. A load reads the DATA memory, so .rodata — string
# literals, const tables — must be in DMEM even though it is read-only.
# Putting it beside the code, as a single-memory script would, makes every
# string read return an instruction word.
#
# The I/O words and the stack top reach assembly as linker SYMBOLS, the way
# they reach C as macros in the generated header, so crt0.S states no address
# of its own.

from __future__ import annotations

from .layout import MemoryLayout
from .render import render_file

TEMPLATE_NAME = "link.ld.in"


def render_linker_script(layout: MemoryLayout) -> str:
    """The whole script for this layout, ready to write next to the objects."""
    symbols = "\n".join(f"__mmio_{name:<8} = 0x{addr:08x};"
                        for name, addr in layout.mmio_addrs.items())

    return render_file(TEMPLATE_NAME,
                       {"IMEM_BASE"   : f"0x{layout.imem_base:08x}",
                        "IMEM_BYTES"  : layout.imem_bytes,
                        "DMEM_BASE"   : f"0x{layout.dmem_base:08x}",
                        "DATA_BYTES"  : layout.data_bytes,
                        "MMIO_SYMBOLS": symbols,
                        "STACK_TOP"   : f"0x{layout.stack_top:08x}"})
