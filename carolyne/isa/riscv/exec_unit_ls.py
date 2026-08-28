# LSExecUnit — loads and stores. NO exec_stage yet: the memory story is not
# finished, so the base's NotImplementedError stands and a complex built on
# this unit refuses at elaboration rather than building nothing.

from __future__ import annotations

from ..exec_unit import ExecUnitBase


class LSExecUnit(ExecUnitBase):
    """Loads and stores; the body lands with the memory story."""
