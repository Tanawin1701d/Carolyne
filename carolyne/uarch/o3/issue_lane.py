# IssueLane — one reservation station and the execution complexes it issues
# into, plus the builder that makes the whole back end's set of them.
#
# A station may feed several execution units (only out of order — an in-order
# station feeds exactly one, config.RsvSpec), and each unit has an issue path
# of its own: its own slot in the station, its own winner, its own arbiter. So
# a station and its complexes are built together and read back together.
#
# The lane WIRES ITSELF (`connect`), the way every block of the core does: the
# station and the complexes are the two halves of one handshake, so the pairing
# has one home instead of a loop at the call site.
#
# A NamedTuple, not a dataclass, and that is load-bearing for the SIM: the
# manifest descends into a Module, a list and a TUPLE, and answers None for
# anything else (`sim_manifest._attr_node`), so a dataclass would hide every
# station and complex from KSim. As a tuple the lane is walked, and the reader
# reaches a station at `issue_lanes[k][0]` and a complex at `[k][1][u]`.

from typing import NamedTuple, Tuple

from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.exec_unit import ExecUnitO3
from carolyne.uarch.o3.rsv import RsvBase
from carolyne.uarch.o3.rsv_ior import RsvIOR
from carolyne.uarch.o3.rsv_o3 import RsvO3


class IssueLane(NamedTuple):
    """One reservation station and the execution complexes it issues into.

    - `execs` is in the station's UNIT order, which is the order `rsv.connect`
      wants its arbiters and the order each complex reads its issue slot in
    """
    rsv   : RsvBase
    execs : Tuple[ExecUnitO3, ...]

    def connect(self, core) -> None:
        """Wire the lane up: each complex to the core, the station to the
        complexes.

        - a complex calls back into the core for the declare fan-outs
          (mispredict, resolve, fin, writeback), which land core-wide
        - the station takes one arbiter per unit, in unit order, so a busy
          unit stalls its own issue path and nothing else
        """
        for exu in self.execs:
            exu.connect(core)
        self.rsv.connect(*(exu.exec_meta for exu in self.execs))


def exec_labels(rsv_idx: int, rsv_spec) -> Tuple[str, ...]:
    """A name per complex of one station: the unit it runs, and which COPY of
    that unit it is when the station holds several.

    - one alu on the station reads `exu0_alu`, two read `exu0_alu0` /
      `exu0_alu1` — the copy number only appears where it says something
    """
    names  = [unit.name for unit in rsv_spec.exec_unit]
    labels = []
    for unit_idx, name in enumerate(names):
        copy = f"{names[:unit_idx].count(name)}" if names.count(name) > 1 else ""
        labels.append(f"exu{rsv_idx}_{name}{copy}")
    return tuple(labels)


def build_issue_lanes(config: CPUO3_Config) -> Tuple[IssueLane, ...]:
    """One lane per RsvSpec: the station, and one complex per unit it feeds.

    - the spec's own `issue_o3` picks the station policy, and its POSITION is
      the rsv_id a dispatch lane names, so the lanes stay in spec order
    - a complex is named by the UNIT it runs, never by a bare ordinal, and
      by which COPY of that unit it is when the station holds more than one
    - declares hardware, so call it from the @init of the module that holds
      the lanes
    """
    lanes = []
    for rsv_idx, rsv_spec in enumerate(config.rsv_specs):
        station_cls = RsvO3 if rsv_spec.issue_o3 else RsvIOR
        rsv         = station_cls(config, rsv_spec, f"rsv{rsv_idx}", rsv_idx)
        execs       = tuple(ExecUnitO3(config, rsv, rsv_spec, unit_idx, label)
                            for unit_idx, label
                            in enumerate(exec_labels(rsv_idx, rsv_spec)))
        lanes.append(IssueLane(rsv, execs))
    return tuple(lanes)
