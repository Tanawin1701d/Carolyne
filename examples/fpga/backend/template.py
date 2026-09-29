# fill_template — one template file to one output file, backend-neutral.
#
# Two substitutions, in this order per line:
#   blocks        a line holding a MARKER is replaced whole by what its
#                 callable returns, given the line's indentation — a marker is a
#                 comment in the template's own language, so the template stays
#                 a valid tcl / Verilog / Python file
#   replacements  a TOKEN is replaced by its value wherever it appears
#
# Tokens are plain substrings, applied in dict order: list a token that contains
# another BEFORE it.

from __future__ import annotations

import os
from typing import Callable, Dict, Optional

Block = Callable[[str], str]        # indentation in, generated text out


def fill_template(template_path : str,
                  out_path      : str,
                  replacements  : Optional[Dict[str, str]] = None,
                  blocks        : Optional[Dict[str, Block]] = None) -> str:
    """Write the filled template to `out_path`; return the text written."""
    replacements = replacements or {}
    blocks       = blocks or {}
    with open(template_path, "r", encoding="utf-8") as handle:
        text = fill_text(handle.read(), replacements, blocks)
    directory = os.path.dirname(out_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def fill_text(text: str, replacements: Dict[str, str], blocks: Dict[str, Block]) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        indent = line[:len(line) - len(line.lstrip(" "))]
        block  = next((fn for marker, fn in blocks.items() if marker in line), None)
        if block is not None:
            generated = block(indent)
            out.append(generated if generated.endswith("\n") else generated + "\n")
            continue
        for token, value in replacements.items():
            line = line.replace(token, str(value))
        out.append(line)
    return "".join(out)
