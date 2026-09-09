# Repo root on sys.path, so tests can import `examples.*`.
#
# `carolyne` is an editable install, but pyproject's package discovery is
# `include = ["carolyne*"]`, so `examples/` is deliberately not installed.
# A test that exercises an example has to reach it by path.

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
