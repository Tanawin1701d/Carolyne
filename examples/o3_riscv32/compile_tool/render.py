# Filling in the files under template/.
#
# Markers are @NAME@ rather than Python's own {name}, because both templates
# are written in languages made of braces — a linker script's SECTIONS and
# output sections, a C header's function bodies — and str.format would need
# every one of those doubled. That escaping is what used to keep both
# templates trapped inside .py files as string constants.
#
# Shared by ldscript.py and cheader.py, which are siblings: neither should
# have to import the other to reach this.

from __future__ import annotations

import os
import re

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "template")

_MARKER = re.compile(r"@([A-Z0-9_]+)@")


def read_template(name: str) -> str:
    """One template file's text, by name."""
    with open(os.path.join(TEMPLATE_DIR, name)) as handle:
        return handle.read()


def fill_template(text: str, values: dict, where: str) -> str:
    """Replace every @NAME@ marker, refusing a mismatch either way.

    - a marker nothing fills would reach the compiler or the linker as a
      literal @NAME@ and fail there, far from the cause
    - a value no marker uses means a marker was renamed and one caller was
      not, which is the same bug seen from the other side
    """
    seen    = set()
    missing = set()

    def swap(match: re.Match) -> str:
        name = match.group(1)
        seen.add(name)
        if name not in values:
            missing.add(name)
            return match.group(0)
        return str(values[name])

    filled = _MARKER.sub(swap, text)

    unused = set(values) - seen
    if missing or unused:
        raise KeyError(
            f"{where}: " +
            ", ".join(filter(None, [
                f"nothing fills {sorted(missing)}" if missing else "",
                f"no marker uses {sorted(unused)}" if unused else ""])))
    return filled


def render_file(name: str, values: dict) -> str:
    """Read one template and fill it, naming it if anything is missing."""
    return fill_template(read_template(name), values, where=name)
