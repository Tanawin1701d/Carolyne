# Decode — the decoded-µop record the front end carries, one row per front-end
# lane, built from the ISA description the way the ROB's and a station's tables
# are.
#
# The fixed half is what every decoded µop carries whatever it is: whether the
# lane holds one at all, where it came from, where the next instruction is, and
# WHICH µop of the ISA's vocabulary it is (`uop_idx`, the id the whole core
# speaks in after decode — no raw ISA bits ride along, uop_contract.md §2).
#
# The part that varies with the ISA is one field group per atomic operand,
# core-wide: decode happens before a µop is routed anywhere, so the record must
# be able to carry ANY µop the ISA declares.
#
#   src   active_<n>       this µop fills that slot at all
#         valid_<n>        its value is already in hand, so rename has nothing
#                          to look up and it reaches its station already woken
#         ar_idx_<n>       the architectural register the decoder extracted
#         data_<n>         the value itself
#   dest  active_<n>       this µop writes that slot
#         wb_required_<n>  the writeback must land before the instruction retires
#         ar_idx_<n>       the architectural register rename will map
#
# NO pr_idx anywhere: decode is BEFORE rename, so a physical index does not
# exist yet — ar_idx is what rename reads and pr_idx is what it answers.
#
# A group carries only the kinds its core can answer: `ar_idx` rides on
# `has_arch`, since a slot naming a µtemp only has no architectural class, and
# `data` on `has_imm`, which is how an immediate reaches the record (RV32I's
# ImmTarget). LIMIT: `has_imm` is true of ANY µtemp target, and a real µtemp is
# not known at decode but produced by an earlier µop of the same crack — the
# description layer cannot yet tell the two apart (the open `Uop.imm` gap), so
# the field is there either way and `valid_<n>` is what the decoder must answer
# honestly per slot.

from kathryn import *

from carolyne.isa import AtomicOperand, IsaBase
from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.operand_field import (ACTIVE, AR_IDX, DATA, WB_REQUIRED,
                                             VALID, field_name,
                                             named_atomic_operands,
                                             operand_fields as build_fields)


class DecodeEntryBase(Karray):

    valid   = kaf(1)
    pc      = kaf()
    npc     = kaf()
    uop_idx = kaf()


def decode_atm_operands(isa: IsaBase) -> tuple:
    """Every atomic operand the ISA's µops fill, sources then destinations.

    Core-wide, not per unit: a decoded µop has not been routed to a station
    yet, so the record has to hold whatever it turns out to be.
    """
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

    if atm_operand.has_arch:
        kinds += (AR_IDX,)
    if atm_operand.is_src and atm_operand.has_imm:
        kinds += (DATA,)

    return build_fields(config, atm_operand, kinds, "decode")


def decode_entry_shape(config: CPUO3_Config) -> tuple:
    """The entry class decode uses, and the widths of every field it holds.

    Shared by the table and by any wire row a stage builds of the same shape,
    so the two cannot drift.
    """
    fields = {"pc"     : config.pc_width,
              "npc"    : config.pc_width,       # where the next instruction sits
              "uop_idx": config.uop_idx_width}  # which µop of the ISA this is

    for atm_operand in decode_atm_operands(config.isa):
        fields.update(decode_operand_fields(config, atm_operand))
    return DecodeEntryBase, fields


def build_decode_table(config: CPUO3_Config, name: str = "decode"):
    """The decode stage's record: a Karray of `config.fe_lanes` rows.

    Declares hardware, so it must be called from inside an open Kathryn module
    scope — the @init of the module that owns decode.
    """
    entry_cls, fields = decode_entry_shape(config)
    table = entry_cls(HwComponentType.REG, (config.fe_lanes,), name, **fields)

    # Powers up empty, with no slot claimed by anything.
    resets = {"valid": 0}
    for atm_operand in decode_atm_operands(config.isa):
        resets[field_name(ACTIVE, atm_operand)] = 0
    return table.reset(**resets)
