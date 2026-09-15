# Sim-side helpers the *SimProbe classes share: reading one handle, and one
# manifest child the model may not have exposed.

from __future__ import annotations

from typing import Any, Optional


def read_value(handle: Any) -> Optional[int]:
    value = handle.value
    if not getattr(value, "is_resolvable", True):   # X/Z in the simulator: an unwritten register
        return None
    return int(value)


def child_or_none(sim_reps: Any, name: str) -> Optional[Any]:
    return getattr(sim_reps, name, None)                # None: the model did not expose that signal
