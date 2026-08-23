# Rsv — one reservation station's entry table, built from the ISA description
# and the machine's RsvSpec.
#
# The entry classes state the shape every station has; `build_rsv_table` adds
# the per-operand fields, which are the part that varies with the ISA: one
# group per AtomicOperand the station's exec units read or write, named after
# that atomic operand (`valid_src_1`, `pr_idx_src_1`, `data_src_1`). The name
# is the stem, so it must be unique — IsaBase enforces that across the ISA.
#
#   src on a register class   valid_<n>  pr_idx_<n>  data_<n>
#   src on a µtemp only       data_<n>              (no PRF entry to wake on:
#                                                    the value rides with the µop)
#   dest                                       pr_idx_<n>
#   dest, writeback required  wb_required_<n>  pr_idx_<n>
#
# `uop_idx` names one µop of the ISA's vocabulary, so it is sized from the
# template count and means the same µop anywhere in the CPU core.
# `rob_des_idx` names the ROB entry the µop belongs to, sized from the buffer's
# depth — it rides in from dispatch and is what a writeback reports against.
# `track` is an out-of-order station's age order, ceil_log2 of its own rows.
#
# The PC is NOT in the base: which stations carry one is a question of what
# KIND of station it is (`RsvSpec.rsv_type`), so `pc`/`npc` arrive as added
# fields from `rsv_spec.entry_fields()` along with whatever the machine put on
# top. A load/store station carries neither.

from kathryn import *

from carolyne.isa import AtomicOperand, IsaBase
from carolyne.uarch.common import ceil_log2
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec
from carolyne.uarch.o3.operand_field import (DATA, PR_IDX, WB_REQUIRED, VALID,
                                             operand_fields as build_fields,
                                             require_named)


class RsvEntryBase(Karray):
    valid    = kaf(1)
    # speculative
    is_spec  = kaf(1)
    spec_tag = kaf()
    # operation
    uop_idx  = kaf()
    # which ROB entry this µop belongs to — what writeback marks finished and
    # what commit retires
    rob_des_idx = kaf()


class RsvO3Entry(RsvEntryBase):

    is_lower_track = kaf(1)
    track          = kaf()


# IOR = inorder
class RsvIOREntry(RsvEntryBase):
    pass


def station_atm_operands(isa: IsaBase, rsv_spec: RsvSpec) -> tuple:
    """Every atomic operand the station's units read or write, srcs then dests.

    Deduped by identity — two units of one station may run µops that share an
    atomic operand — and held to unique, non-empty names, since a name becomes
    a field name.
    """
    atm_operands, by_name = [], {}
    for want_src in (True, False):
        for unit in rsv_spec.exec_unit:
            found = (isa.src_atomic_operands_for(unit) if want_src
                     else isa.dest_atomic_operands_for(unit))
            for atm_operand in found:
                if any(seen is atm_operand for seen in atm_operands):
                    continue
                require_named(atm_operand, f"reservation station '{rsv_spec.label}'")
                if atm_operand.name in by_name:
                    raise ValueError(
                        f"reservation station '{rsv_spec.label}': two atomic operands "
                        f"named '{atm_operand.name}' — one name, one set of fields")
                by_name[atm_operand.name] = atm_operand
                atm_operands.append(atm_operand)
    return tuple(atm_operands)


def operand_fields(config: CPUO3_Config,
                   rsv_spec: RsvSpec,
                   atm_operand: AtomicOperand) -> dict:
    """The entry fields one atomic operand contributes, as kaf() specs.

    Which KINDS a waiting entry keeps, in the order they read: a source waits
    on a value, so it carries the wake pair and the value; a µtemp source has
    no physical register to wake on, so the value rides alone. A destination
    carries only where its result goes, plus the bit that says the write is
    required. The names and widths themselves are operand_field's.
    """
    if atm_operand.is_src:
        kinds = (VALID, PR_IDX, DATA) if atm_operand.has_arch else (DATA,)
    elif atm_operand.is_write_required:
        kinds = (WB_REQUIRED, PR_IDX)
    else:
        kinds = (PR_IDX,)

    return build_fields(config, atm_operand, kinds,
                        f"reservation station '{rsv_spec.label}'")


def rsv_entry_shape(config: CPUO3_Config, rsv_spec: RsvSpec) -> tuple:
    """The entry class one station uses, and the widths of every field it holds.

    Shared by the table and the issued-entry slot, so the two cannot drift.
    """
    entry_cls = RsvO3Entry if rsv_spec.issue_o3 else RsvIOREntry

    fields = {"spec_tag"   : config.sptag_len,
              "uop_idx"    : config.uop_idx_width,   # which µop of the ISA
              "rob_des_idx": config.rob_idx_width}   # which ROB entry it is

    if rsv_spec.issue_o3:
        if rsv_spec.size < 2:
            raise ValueError(
                f"reservation station '{rsv_spec.label}': out-of-order issue needs at "
                f"least 2 entries, {rsv_spec.size} leaves the age track 0 bits wide")
        fields["track"] = ceil_log2(rsv_spec.size)

    for atm_operand in station_atm_operands(config.isa, rsv_spec):
        fields.update(operand_fields(config, rsv_spec, atm_operand))

    # The station KIND's fields and the machine's own, added last so a name
    # colliding with anything already in the record is caught here — the spec
    # can only check them against each other, never against an operand's.
    declared = {name for name, _ in entry_cls.__karray_fields__}
    for name, width in rsv_spec.entry_fields(config.pc_width):
        if name in fields or name in declared:
            raise ValueError(
                f"reservation station '{rsv_spec.label}': entry field '{name}' is "
                f"already in the record — a name is one set of bits")
        fields[name] = kaf(width)
    return entry_cls, fields


def rsv_field_names(config: CPUO3_Config, rsv_spec: RsvSpec) -> tuple:
    """Every field one station's entries carry, declared ones then added ones.

    What a caller needs to copy a row field by field — the spelling that lets
    one write substitute a field instead of layering a second write on top of a
    whole-row copy, which equal priorities would order the wrong way round.
    """
    entry_cls, fields = rsv_entry_shape(config, rsv_spec)
    declared = tuple(name for name, _ in entry_cls.__karray_fields__)
    added    = tuple(name for name, spec in fields.items() if name not in declared)
    return declared + added


def build_rsv_table(config: CPUO3_Config, rsv_spec: RsvSpec, name: str = ""):
    """One station's entry table: a Karray of `rsv_spec.size` rows.

    Declares hardware, so it must be called from inside an open Kathryn module
    scope — the @init of the module that owns the station.
    """
    entry_cls, fields = rsv_entry_shape(config, rsv_spec)
    table = entry_cls(HwComponentType.REG, (rsv_spec.size,),
                      name or f"rsv_{rsv_spec.label.replace('/', '_')}",
                      **fields)
    return table.reset(valid=0)     # a station powers up empty


def rsv_id_width(config: CPUO3_Config) -> int:
    """Bits naming one station of the machine — how wide the dispatch bus's
    `rsv_id` is. At least one: a single-station machine still has to carry the
    field a lane compares against."""
    return max(1, ceil_log2(len(config.rsv_specs)))


def build_rsv_slot(config: CPUO3_Config, rsv_spec: RsvSpec, name: str = ""):
    """One row of the same shape — the entry a station issued this cycle."""
    entry_cls, fields = rsv_entry_shape(config, rsv_spec)
    slot = entry_cls(HwComponentType.REG, (1,),
                     name or f"rsv_{rsv_spec.label.replace('/', '_')}_exec",
                     **fields)
    return slot.reset(valid=0)
