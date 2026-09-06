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
#   uop_idx      WHICH µop of the ISA's vocabulary it is (no raw ISA bits are
#                past decode, uop_contract.md §2)
#   rob_des_idx  the ROB entry it was allocated, what writeback reports against
#   rsv_id       the station it is aimed at, which is what lets every station
#                read every lane and take only the ones naming it
#   is_branch    the two barriers commit groups against
#   is_store
#   pc           where the instruction is, and where the next one is
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
# Why the table drops what it drops:
#   - a SOURCE never carries `wb_required`. That bit is a destination's
#     promise that the writeback lands before the instruction retires, and a
#     source writes nothing. A destination carries it only on a DEST_W_REQ
#     core; operand_field drops it on a plain DEST.
#   - a DESTINATION never carries `valid` or `data`. It waits for nothing, and
#     at dispatch its value does not exist yet: the FU has not run.
#   - NO INDEX WITHOUT A CLASS. `pr_idx` and `ar_idx` name a register of a
#     class, which a µtemp does not have. That is operand_field's rule, and it
#     refuses the two rather than sizing them zero.

from typing import Optional

from kathryn import *

from carolyne.isa import AtomicOperand
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, DATA, PR_IDX,
                                             VALID, WB_REQUIRED,
                                             named_atomic_operands,
                                             operand_fields)
from carolyne.uarch.o3.rsv_helper import rsv_id_width

# In operand_field.KIND_ORDER, which is the order the fields land in — every
# record here lists its kinds the same way, so the groups can be read against
# each other.
SRC_KINDS  = (ACTIVE, VALID, DATA, PR_IDX, AR_IDX)
DEST_KINDS = (ACTIVE, WB_REQUIRED, PR_IDX, AR_IDX)

# The two that need an architectural class to mean anything.
_INDEX_KINDS = (PR_IDX, AR_IDX)


class DispatchEntryBase(Karray):

    #  HALF A BUS — the fields below are the machine's, the same for every
    #  ISA. build_dispatch() ADDS one group per atomic operand the ISA
    #  declares, core-wide:
    #
    #      per src core    active_<n>  valid_<n>  data_<n>
    #                      pr_idx_<n>  ar_idx_<n>
    #      per dest core   active_<n>  wb_required_<n>
    #                      pr_idx_<n>  ar_idx_<n>
    #
    #  <n> is the core's own name, and a group lands in operand_field's
    #  KIND_ORDER; both indexes drop on a core that only ever names a µtemp,
    #  wb_required on a plain DEST (only a DEST_W_REQ core stores the bit).
    #  RV32I, whose dest_1 is a plain DEST, builds:
    #
    #      valid  pc  npc  uop_idx  is_branch  is_store  rsv_id  <- declared
    #      is_spec  spec_tag  rob_des_idx
    #      active_src_1   valid_src_1  data_src_1                 <- added
    #                     pr_idx_src_1  ar_idx_src_1
    #      active_src_2   valid_src_2  data_src_2
    #                     pr_idx_src_2  ar_idx_src_2
    #      active_src_3   valid_src_3  data_src_3
    #      active_dest_1  pr_idx_dest_1  ar_idx_dest_1
    #
    #  Which is why a reader downstream copies BY NAME (dispatch_field_names)
    #  and never by position.

    # the DECODE half — what convert_lane's k2k copy fills off the decode
    # row, declared in DecodeEntryBase's own order so the two records read
    # alike
    valid       = kaf(1)
    pc          = kaf()
    npc         = kaf()
    uop_idx     = kaf()
    is_branch   = kaf(1)
    is_store    = kaf(1)
    rsv_id      = kaf()     # which station the lane is aimed at

    # the RENAME half — what decode cannot answer; rename/allocation
    # overlays these at its own rung
    is_spec     = kaf(1)
    spec_tag    = kaf()
    rob_des_idx = kaf()     # the ROB entry the µop belongs to


def dispatch_operand_kinds(atm_operand: AtomicOperand) -> tuple:
    """The field kinds one operand's group carries — role first, then target."""
    kinds = SRC_KINDS if atm_operand.is_src else DEST_KINDS
    if atm_operand.has_arch:
        return kinds
    return tuple(kind for kind in kinds if kind not in _INDEX_KINDS)


def dispatch_entry_shape(config: CPUO3_Config) -> tuple:
    """The bus class, and the widths of every field it holds.

    Shared by the bus and by anything built of the same shape, so the two
    cannot disagree.
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
    return DispatchEntryBase, fields


def dispatch_field_names(config: CPUO3_Config) -> tuple:
    """Every field one dispatch lane carries, declared ones then added ones.

    - the bus is core-wide, so a station's record is a subset of it plus what
      the station writes itself
    """
    entry_cls, fields = dispatch_entry_shape(config)
    declared = tuple(name for name, _ in entry_cls.__karray_fields__)
    added    = tuple(name for name in fields if name not in declared)
    return declared + added


def build_dispatch(config: CPUO3_Config, lanes: Optional[int] = None,
                   name: str = "dispatch"):
    """The dispatch bus: `lanes` wire rows, one per front-end lane.

    - declares hardware: call it inside an open Kathryn module scope
    """
    entry_cls, fields = dispatch_entry_shape(config)
    lanes = config.fe_lanes if lanes is None else lanes
    return entry_cls(HwComponentType.WIRE, (lanes,), name, **fields)
