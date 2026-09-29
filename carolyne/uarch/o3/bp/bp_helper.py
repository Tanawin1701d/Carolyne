# The bp record — the per-branch fields a predictor needs carried from fetch to
# the branch station. The ONE place they are sized and checked; every record
# that carries them calls this:
#
#   fetch_helper     every lane row        written by Fetch from BpPrediction.meta
#   decode_helper    every lane row        copied by uop_decode
#   dispatch_helper  every bus lane        copied by convert_lane's k2k
#   rsv_helper       RSV_BRANCH entries    copied by the station's k2k write
#
# Added with kaf(): no Karray class body declares them, because the set is the
# predictor's and not the engine's.

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Tuple

from kathryn import kaf

from carolyne.uarch.o3.bp.bp_spec import BP_FIELD_PREFIX

if TYPE_CHECKING:
    from carolyne.uarch.o3.config import CPUO3_Config


def bp_field_widths(config: CPUO3_Config) -> Dict[str, int]:
    """The predictor's record as {field name: width}, every entry checked."""
    where          = f"branch predictor {config.bp_spec.label}"
    width_by_field = {}
    for entry in config.bp_spec.meta_fields(config):
        name, width = check_bp_field(entry, where)
        if name in width_by_field:
            raise ValueError(f"{where}: two fields named '{name}'")
        width_by_field[name] = width
    return width_by_field

def bp_field_names(config: CPUO3_Config) -> Tuple[str, ...]:
    return tuple(bp_field_widths(config))

def bp_entry_fields(config: CPUO3_Config) -> dict:
    """The record as kaf() specs, ready to merge into a record's field dict."""
    return {name: kaf(width) for name, width in bp_field_widths(config).items()}

def check_bp_field(entry, where: str) -> Tuple[str, int]:
    """One (name, width) pair of a predictor's record, held to what a record field can be.

    - the `bp_` prefix keeps the name apart from the engine's own fields
    """
    if not (isinstance(entry, tuple) and len(entry) == 2):
        raise TypeError(f"{where}: meta_fields holds (name, width) pairs, got {entry!r}")
    name, width = entry
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError(f"{where}: field name {name!r} is not an identifier")
    if not name.startswith(BP_FIELD_PREFIX):
        raise ValueError(
            f"{where}: field '{name}' must start with '{BP_FIELD_PREFIX}' — "
            f"the prefix keeps it apart from the engine's own fields")
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError(f"{where}: field '{name}' needs an int width >= 1, got {width!r}")
    return name, width