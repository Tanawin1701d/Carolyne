# The C header a program includes, filled in from the MemoryLayout.
#
# The header itself is template/carolyne_io.h.in, not a string in here: it is
# C, so it should be readable and compilable as C.
#
# The I/O addresses reach C from the same object the linker script and the
# harness read, so a program and the thing watching the store port cannot
# disagree about where a character goes.
#
# Each door is a volatile pointer CONSTANT, not a variable holding an address:
# the store compiles to `lui` + `sw` with nothing loaded first, and the linker
# usually relaxes it further to one gp-relative instruction. RIDECORE's
# `volatile const unsigned int disp_addr = 0x0;` costs an extra `lw` on every
# character, because the compiler must read the variable before storing
# through it.

from __future__ import annotations

from .layout import MemoryLayout
from .render import render_file

TEMPLATE_NAME = "carolyne_io.h.in"

_DOOR_COMMENT = {"putchar": "one character, written as its byte value",
                 "putint" : "one signed integer, printed in decimal",
                 "exit"   : "stop the machine; the value is the exit code"}


def render_c_header(layout: MemoryLayout) -> str:
    """The whole header for this layout, ready to write beside the sources."""
    doors = "\n".join(
        f"/* {_DOOR_COMMENT.get(name, name)} */\n"
        f"#define CAROLYNE_{name.upper():<8} "
        f"(*(volatile unsigned int *)0x{addr:08x}u)"
        for name, addr in layout.mmio_addrs.items())

    return render_file(TEMPLATE_NAME,
                       {"IMEM_BASE" : f"0x{layout.imem_base:08x}",
                        "IMEM_BYTES": layout.imem_bytes,
                        "DMEM_BASE" : f"0x{layout.dmem_base:08x}",
                        "DATA_BYTES": layout.data_bytes,
                        "STACK_TOP" : f"0x{layout.stack_top:08x}",
                        "DOORS"     : doors})
