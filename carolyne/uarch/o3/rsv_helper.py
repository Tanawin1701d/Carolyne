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
#   dest                                 pr_idx_<n>
#   dest, write required      required_<n>  pr_idx_<n>
#
# `uop_idx` names one µop of the ISA's vocabulary, so it is sized from the
# template count and means the same µop anywhere in the CPU core. `track` is an
# out-of-order station's age order, ceil_log2 of its own row count.

from kathryn import *

from carolyne.isa import AtomicOperand, IsaBase
from carolyne.uarch.common import ceil_log2
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec


class RsvEntryBase(Karray):
    valid    = kaf(1)
    # speculative
    is_spec  = kaf(1)
    spec_tag = kaf()
    # operation
    uop_idx  = kaf()
    # program counter
    pc       = kaf()


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
                if not atm_operand.name:
                    raise ValueError(
                        f"reservation station '{rsv_spec.label}': a {atm_operand.role} "
                        f"atomic operand has no name, so its entry fields cannot be "
                        f"named — name the ones the ISA declares")
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
    """The entry fields one atomic operand contributes, as kaf() specs."""
    name = atm_operand.name

    if atm_operand.is_src:
        if not atm_operand.has_arch:                    # a µtemp/immediate source
            return {f"data_{name}": kaf(atm_operand.intermediate.width)}
        return {f"valid_{name}" : kaf(1),
                f"pr_idx_{name}": kaf(config.phy_idx_width(atm_operand.reg_file)),
                f"data_{name}"  : kaf(atm_operand.reg_file.width)}

    if not atm_operand.has_arch:
        raise ValueError(
            f"reservation station '{rsv_spec.label}': destination atomic operand "
            f"'{name}' targets a µtemp only, and the config sizes a physical file per "
            f"register class — there is no index width for it")
    fields = {}
    if atm_operand.is_write_required:
        fields[f"required_{name}"] = kaf(1)
    fields[f"pr_idx_{name}"] = kaf(config.phy_idx_width(atm_operand.reg_file))
    return fields


def build_rsv_table(config: CPUO3_Config, rsv_spec: RsvSpec, name: str = ""):
    """One station's entry table: a Karray of `rsv_spec.size` rows.

    Declares hardware, so it must be called from inside an open Kathryn module
    scope — the @init of the module that owns the station.
    """
    entry_cls = RsvO3Entry if rsv_spec.issue_o3 else RsvIOREntry

    fields = {"spec_tag": config.sptag_len,
              "uop_idx" : config.uop_idx_width,      # which µop of the ISA
              "pc"      : config.pc_width}

    if rsv_spec.issue_o3:
        if rsv_spec.size < 2:
            raise ValueError(
                f"reservation station '{rsv_spec.label}': out-of-order issue needs at "
                f"least 2 entries, {rsv_spec.size} leaves the age track 0 bits wide")
        fields["track"] = ceil_log2(rsv_spec.size)

    for atm_operand in station_atm_operands(config.isa, rsv_spec):
        fields.update(operand_fields(config, rsv_spec, atm_operand))

    table = entry_cls(HwComponentType.REG, (rsv_spec.size,),
                      name or f"rsv_{rsv_spec.label.replace('/', '_')}",
                      **fields)
    return table.reset(valid=0)     # a station powers up empty
