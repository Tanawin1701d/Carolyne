# Fetch — the fetched-instruction record the front end fills, one row per
# front-end lane, built from the config the way decode's and the ROB's tables
# are.
#
# It is the ONE place raw ISA bits are legal: `instr` is the encoded word as
# memory returned it, and decode is what turns it into a µop id. Nothing
# downstream of decode may carry it (uop_contract.md §2).
#
#   pc     where this instruction sits, sized from the ISA's pc_width
#   instr  the encoded word, ilen_bytes * 8 wide
#
# NO valid bit: a lane's occupancy is the fetch stage's `pip` grant, so a field
# beside it would be a second answer to one question. Both widths are sized at
# instantiation and neither has a default — a 32 that happens to be right for
# RV32I is a silent wrong answer for a 64-bit ISA, the same bargain
# `IsaBase.pc_width` makes.

from kathryn import *

from carolyne.uarch.o3.config import CPUO3_Config


class FetchEntryBase(Karray):

    #  THE WHOLE RECORD — build_fetch_table() adds NOTHING:
    #
    #      pc  instr
    #
    #  Fetch runs before decode, so no field here varies with the ISA's
    #  operands; the builder only SIZES these two (pc_width, ilen_bytes * 8).
    #  Unsized kaf() = every instantiation must state a width, which is what
    #  keeps a 64-bit ISA from silently inheriting RV32I's 32.
    pc    = kaf()
    instr = kaf()


def fetch_entry_shape(config: CPUO3_Config) -> tuple:
    """The entry class fetch uses, and the widths of every field it holds.

    Shared by the table and by any wire row a stage builds of the same shape,
    so the two cannot drift.
    """
    return FetchEntryBase, {"pc"   : config.pc_width,
                     "instr": config.instr_width}   # ilen_bytes * 8


def build_fetch_table(config: CPUO3_Config, name: str = "fetch"):
    """The fetch stage's record: a Karray of `config.fe_lanes` rows.

    Declares hardware, so it must be called from inside an open Kathryn module
    scope — the @init of the module that owns fetch.
    """
    entry_cls, fields = fetch_entry_shape(config)
    return entry_cls(HwComponentType.REG, (config.fe_lanes,), name, **fields)
