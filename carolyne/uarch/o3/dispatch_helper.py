# Dispatch — the bus from rename to the back end, one wire row per front-end
# lane. It carries a field group for every atomic operand the ISA uses,
# core-wide: a lane is shaped before it is routed, so it has to hold whatever
# the µop turns out to be.
#
# The FIXED half is the machine's own, the fields every reader downstream needs
# beside the operand groups:
#
#   valid        this lane carries a µop this cycle
#   is_spec      it is under an open speculation, spec_tag says which ones
#   spec_tag
#   uop_idx      WHICH µop of the ISA's vocabulary it is (no raw ISA bits ride
#                past decode, uop_contract.md §2)
#   rob_des_idx  the ROB entry it was allocated, what writeback reports against
#   rsv_id       the station it is aimed at, which is what lets every station
#                read every lane and take only the ones naming it
#   is_branch    the two barriers commit groups against
#   is_store
#   pc           where the instruction sits, and where the next one does
#   npc
#
# WHICH KINDS an operand group carries follows from the operand's ROLE and its
# TARGET:
#
#   src,  register class   valid  data  pr_idx  ar_idx  active
#   src,  immediate only   valid  data                  active
#   dest, register class                pr_idx  ar_idx  active  wb_required
#   dest, µtemp only                                    active  wb_required
#
# A SOURCE never carries `wb_required`: it is a destination's promise that the
# writeback lands before the instruction retires, and a source writes nothing.
#
# A DESTINATION never carries `valid` or `data`: it is not waiting on anything,
# and at dispatch its value does not exist yet — the FU has not run.
#
# NO INDEX WITHOUT A CLASS: `pr_idx` and `ar_idx` name a register OF A CLASS,
# which a µtemp has not got, so an operand that only ever names one carries
# neither. That is `operand_field`'s rule, not a choice made here — it refuses
# the two rather than sizing them zero.

from typing import Optional

from kathryn import *

from carolyne.isa import AtomicOperand
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, DATA, PR_IDX,
                                             VALID, WB_REQUIRED,
                                             named_atomic_operands,
                                             operand_fields)
from carolyne.uarch.o3.rsv_helper import rsv_id_width

SRC_KINDS  = (VALID, DATA, PR_IDX, AR_IDX, ACTIVE)
DEST_KINDS = (PR_IDX, AR_IDX, ACTIVE, WB_REQUIRED)

# The two that need an architectural class to mean anything.
_INDEX_KINDS = (PR_IDX, AR_IDX)


class DispatchBase(Karray):

    valid       = kaf(1)
    # speculative
    is_spec     = kaf(1)
    spec_tag    = kaf()
    # operation
    uop_idx     = kaf()
    # where it goes: the ROB entry it holds, and the station it is aimed at
    rob_des_idx = kaf()
    rsv_id      = kaf()
    # what commit groups against
    is_branch   = kaf(1)
    is_store    = kaf(1)
    # where it came from, and where the next instruction sits
    pc          = kaf()
    npc         = kaf()


def dispatch_operand_kinds(atm_operand: AtomicOperand) -> tuple:
    """The field kinds one operand's group carries — role first, then target."""
    kinds = SRC_KINDS if atm_operand.is_src else DEST_KINDS
    if atm_operand.has_arch:
        return kinds
    return tuple(kind for kind in kinds if kind not in _INDEX_KINDS)


def dispatch_entry_shape(config: CPUO3_Config) -> tuple:
    """The bus class, and the widths of every field it holds.

    Shared by the bus and by anything built of the same shape, so the two
    cannot drift.
    """
    where  = f"dispatch of ISA '{config.isa.name}'"
    fields = {"spec_tag"   : config.sptag_len,
              "uop_idx"    : config.uop_idx_width,   # which µop of the ISA
              "rob_des_idx": config.rob_idx_width,   # which ROB entry it is
              "rsv_id"     : rsv_id_width(config),   # which station it is for
              "pc"         : config.pc_width,
              "npc"        : config.pc_width}

    for atm_operand in named_atomic_operands(config.isa, where):
        fields.update(operand_fields(config, atm_operand,
                                     dispatch_operand_kinds(atm_operand), where))
    return DispatchBase, fields


def dispatch_field_names(config: CPUO3_Config) -> tuple:
    """Every field one dispatch lane carries, declared ones then added ones.

    What a reader needs to know which of ITS fields a lane can fill: the bus is
    core-wide, so a station's record is a subset of it plus whatever the
    station stamps itself.
    """
    entry_cls, fields = dispatch_entry_shape(config)
    declared = tuple(name for name, _ in entry_cls.__karray_fields__)
    added    = tuple(name for name in fields if name not in declared)
    return declared + added


def build_dispatch(config: CPUO3_Config, lanes: Optional[int] = None,
                   name: str = "dispatch"):
    """The dispatch bus: `lanes` wire rows, one per front-end lane.

    Declares hardware, so it must be called from inside an open Kathryn module
    scope — the @init of the module that owns dispatch.
    """
    entry_cls, fields = dispatch_entry_shape(config)
    lanes = config.fe_lanes if lanes is None else lanes
    return entry_cls(HwComponentType.WIRE, (lanes,), name, **fields)
