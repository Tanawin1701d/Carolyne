# Decode — the decoded-µop record the front end carries, one row per front-end
# lane, built from the ISA description the way the ROB's and a station's tables
# are.
#
# The fixed half is what every decoded µop carries, whatever it is:
#
#   valid        the lane holds a µop at all
#   pc / npc     where it came from, and where the next instruction is
#   uop_idx      WHICH µop of the ISA's vocabulary it is: the id the whole core
#                uses after decode, since no raw ISA bits are carried past it
#                (uop_contract.md §2)
#   is_branch    dispatch books a speculation tag against it
#   is_store     with is_branch, the commit barrier the ROB groups on
#   rsv_id       which station it is for; routing is decode's to supply
#
# The part that varies with the ISA is one field group per atomic operand,
# core-wide: decode happens before a µop is routed anywhere, so the record must
# be able to carry ANY µop the ISA declares.
#
#   src   active_<n>       this µop fills that slot at all
#         valid_<n>        its value is already known, so rename has nothing
#                          to look up and it arrives at its station awake
#         ar_idx_<n>       the architectural register the decoder extracted
#         data_<n>         the value itself
#   dest  active_<n>       this µop writes that slot
#         wb_required_<n>  the writeback must land before the instruction
#                          retires — DEST_W_REQ cores only (operand_field
#                          drops the bit on a plain DEST)
#         ar_idx_<n>       the architectural register rename will map
#
# NO pr_idx anywhere: decode is BEFORE rename, so a physical index does not
# exist yet — ar_idx is what rename reads and pr_idx is what it answers.
#
# A group carries only the kinds its core can answer: `ar_idx` needs
# `has_arch`, and `data` needs `has_imm`, which is how an immediate enters the
# record (RV32I's ImmTarget).
#
# LIMIT: `has_imm` is true of ANY µtemp target. A real µtemp is not known at
# decode; it is produced by an earlier µop of the same crack, and the
# description layer cannot yet tell the two apart (the open `Uop.imm` gap). So
# the field is built either way, and `valid_<n>` is what the decoder must
# answer correctly per slot.

from kathryn import *

from carolyne.isa import AtomicOperand, IsaBase
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, DATA, WB_REQUIRED,
                                             VALID, field_name,
                                             named_atomic_operands,
                                             operand_fields as build_fields)
from carolyne.uarch.o3.rsv_helper import rsv_id_width


class DecodeEntryBase(Karray):

    #  HALF A RECORD. build_decode_table() ADDS one group per atomic operand
    #  the ISA declares — BOTH directions, since a decoded µop has not been
    #  routed anywhere yet:
    #
    #      per src core    active_<n>  valid_<n>
    #                      + data_<n>     if the core may name an imm
    #                      + ar_idx_<n>   if the core has an arch class
    #      per dest core   active_<n>  ar_idx_<n>
    #                      + wb_required_<n>  if the core is DEST_W_REQ
    #
    #  <n> is the core's own name, and a group lands in operand_field's
    #  KIND_ORDER. NO pr_idx anywhere: decode runs BEFORE rename. RV32I, whose
    #  cores are src_1 / src_2 / src_3 / dest_1, builds:
    #
    #      valid  pc  npc  uop_idx  is_branch  is_store  rsv_id  <- declared
    #      active_src_1   valid_src_1                ar_idx_src_1 <- added
    #      active_src_2   valid_src_2   data_src_2   ar_idx_src_2
    #      active_src_3   valid_src_3   data_src_3
    #      active_dest_1                             ar_idx_dest_1
    #
    #  (src_1 is always a register, so no data_; src_3 is the immediate, so no
    #  ar_idx_; src_2 is rs2 OR an immediate, so both.)
    valid     = kaf(1)
    pc        = kaf()
    npc       = kaf()
    uop_idx   = kaf()
    is_branch = kaf(1)
    is_store  = kaf(1)      # the ROB's commit barrier groups on it
    rsv_id    = kaf()       # which station the µop is for — routing is
                            # decode's to supply, like branch-ness


def decode_atm_operands(isa: IsaBase) -> tuple:
    """Every atomic operand the ISA's µops fill, sources then destinations."""
    return named_atomic_operands(isa, f"decode of ISA '{isa.name}'")


def decode_operand_fields(config: CPUO3_Config, atm_operand: AtomicOperand) -> dict:
    """The entry fields one core contributes, as kaf() specs.

    A kind is asked for only where the core can answer it: `ar_idx` needs an
    architectural class, `data` a µtemp target. The names and widths themselves
    are operand_field's.
    """
    if atm_operand.is_src:
        kinds = (ACTIVE, VALID)
    else:
        kinds = (ACTIVE, WB_REQUIRED)

    if atm_operand.is_src and atm_operand.has_imm:
        kinds += (DATA,)
    if atm_operand.has_arch:
        kinds += (AR_IDX,)

    return build_fields(config, atm_operand, kinds, "decode")


def decode_entry_shape(config: CPUO3_Config) -> tuple:
    """The entry class decode uses, and the widths of every field it holds.

    Shared by the table and by any wire row a stage builds of the same shape,
    so the two cannot disagree.
    """
    fields = {"pc"     : config.pc_width,
              "npc"    : config.pc_width,       # where the next instruction is
              "uop_idx": config.uop_idx_width,  # which µop of the ISA this is
              "rsv_id" : rsv_id_width(config)}  # sized as the bus's, so the
                                                # k2k copy pairs the two

    for atm_operand in decode_atm_operands(config.isa):
        fields.update(decode_operand_fields(config, atm_operand))
    return DecodeEntryBase, fields


def build_decode_table(config: CPUO3_Config, name: str = "decode"):
    """The decode stage's record: a Karray of `config.fe_lanes` rows.

    Declares hardware, so it must be called from inside an open Kathryn module
    scope: the @init of the module that declares decode.
    """
    entry_cls, fields = decode_entry_shape(config)
    table = entry_cls(HwComponentType.REG, (config.fe_lanes,), name, **fields)

    # Powers up empty, with no slot claimed by anything.
    resets = {"valid": 0}
    for atm_operand in decode_atm_operands(config.isa):
        resets[field_name(ACTIVE, atm_operand)] = 0
    return table.reset(**resets)
