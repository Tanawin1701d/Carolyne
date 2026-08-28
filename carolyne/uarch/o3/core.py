# CoreO3 — the top CPU core module: the block that will contain every block
# (fetch, decode, dispatch, rob, prfs, rts, stations, the exec complexes).
#
# PLACEHOLDER on purpose: the ExecUnitApiO3 landing surface briefly lived
# here and moved onto the complexes the same day (a stage body's api calls
# back to its OWN execution unit — exec_unit.py). Nothing joins this class
# until it is designed.

from kathryn import *

from carolyne.uarch.o3.config import CPUO3_Config


class CoreO3(Module):
    """The whole core. So far: a placeholder holding its config."""

    def __init__(self, config: CPUO3_Config):
        self.config = config
        super().__init__()
