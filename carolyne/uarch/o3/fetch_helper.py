# Fetch — the fetched-instruction record the front end fills, one row per
# front-end lane, built from the config the way decode's and the ROB's tables
# are.
#
# It is the ONE place raw ISA bits are legal: `instr` is the encoded word as
# memory returned it, and decode is what turns it into a µop id. Nothing
# downstream of decode may carry it (uop_contract.md §2).
#
#   valid  this lane's bank answered, and every lower lane's did too
#   pc     where this instruction is, sized from the ISA's pc_width
#   instr  the encoded word, ilen_bytes * 8 wide
#
# `valid` is PER LANE, which the stage's `pip` grant cannot be: a grant says
# the stage moved, not that one bank of several failed to answer.
#
# pc and instr are sized at instantiation and neither has a default — a 32 that
# happens to be right for RV32I is a silent wrong answer for a 64-bit ISA, the
# same rule `IsaBase.pc_width` makes.

from kathryn import *

from carolyne.uarch.o3.config import CPUO3_Config
from carolyne.uarch.o3.common_field import INSTR, PC


class FetchEntryBase(Karray):

    #  THE WHOLE RECORD — build_fetch_table() adds NOTHING:
    #
    #      valid  pc  instr
    #
    #  Fetch runs before decode, so no field here varies with the ISA's
    #  operands; the builder only SIZES pc and instr. Unsized kaf() = every
    #  instantiation must state a width, which keeps a 64-bit ISA from
    #  silently inheriting RV32I's 32.
    valid = kaf(1)
    pc    = kaf()
    instr = kaf()


def fetch_entry_shape(config: CPUO3_Config) -> tuple:
    """The entry class fetch uses, and the widths of every field it holds.
    Shared with any wire row of the same shape, so the two cannot disagree."""
    return FetchEntryBase, {PC: config.pc_width,
                     INSTR: config.instr_width}   # ilen_bytes * 8; valid is 1


def build_fetch_table(config: CPUO3_Config, name: str = "fetch"):
    """The fetch record: `config.fe_lanes` rows. Declares hardware, so call
    it inside an open Kathryn module scope."""
    entry_cls, fields = fetch_entry_shape(config)
    table = entry_cls(HwComponentType.REG, (config.fe_lanes,), name, **fields)
    # Powers up empty: decode reads valid before fetch has written one.
    table.reset(valid=0)
    return table
