# Rob — the reorder buffer's entry table, built from the ISA description and
# the machine config, the way build_rsv_table builds a station's.
#
# The fixed half is what every in-flight instruction carries: whether its
# writeback has landed, whether it is a branch or a store, and its PC (sized
# from the config, since the PC is an ISA fact the config derives).
#
# The part that varies with the ISA is one field group per DESTINATION atomic
# operand — sources are the station's business, not the ROB's, because what
# retires is a WRITE:
#
#   active_<n>     this instruction actually writes that destination
#   required_<n>   the write must have landed before it may retire
#   pr_idx_<n>     the physical register rename gave it
#   ar_idx_<n>     the architectural register it belongs to, which is what
#                  commit writes into the ARF and clears from the RAT
#
# A one-register class (x86 FLAGS) gets NO ar_idx: index_width is 0 there, so
# there is nothing to choose and the elaborator wires the single register.

from kathryn import *

from carolyne.isa import AtomicOperand, IsaBase
from carolyne.uarch.o3.config import CPUO3_Config


class RobEntry(Karray):
    wb_fin    = kaf(1)
    is_branch = kaf(1)
    is_store  = kaf(1)
    pc        = kaf()


def rob_dest_operands(isa: IsaBase) -> tuple:
    """Every destination core the ISA's instructions write, in slot order.

    Core-wide, not per unit: anything that retires passes through this table.
    Deduped by identity, and held to non-empty names, since a name becomes a
    field name.
    """
    dests = []
    for atm_operand in isa.used_atomic_operands():
        if not atm_operand.is_dest:
            continue
        if not atm_operand.name:
            raise ValueError(
                f"ISA '{isa.name}': a {atm_operand.role} operand core has no name, so "
                f"its ROB fields cannot be named — name the cores the ISA declares")
        dests.append(atm_operand)
    return tuple(dests)


def rob_operand_fields(config: CPUO3_Config, atm_operand: AtomicOperand) -> dict:
    """The entry fields one destination core contributes, as kaf() specs."""
    name = atm_operand.name

    if not atm_operand.has_arch:
        raise ValueError(
            f"ROB: destination core '{name}' targets a µtemp only. A µtemp dies at the "
            f"instruction boundary, so it has no architectural register to retire into "
            f"and nothing to put in this table")

    reg_file = atm_operand.reg_file
    fields   = {f"active_{name}"  : kaf(1),
                f"required_{name}": kaf(1),
                f"pr_idx_{name}"  : kaf(config.phy_idx_width(reg_file))}
    # A one-register class has an index width of 0 — no index to store.
    if reg_file.index_width:
        fields[f"ar_idx_{name}"] = kaf(reg_file.index_width)
    return fields


def rob_entry_shape(config: CPUO3_Config) -> tuple:
    """The entry class the ROB uses, and the widths of every field it holds.

    Shared by the table and by any wire row a stage builds of the same shape,
    so the two cannot drift.
    """
    fields = {"pc": config.pc_width}
    for atm_operand in rob_dest_operands(config.isa):
        fields.update(rob_operand_fields(config, atm_operand))
    return RobEntry, fields


def build_rob_table(config: CPUO3_Config, name: str = "rob"):
    """The reorder buffer: a Karray of `config.rob_depth` rows.

    Declares hardware, so it must be called from inside an open Kathryn module
    scope — the @init of the module that owns the ROB.
    """
    entry_cls, fields = rob_entry_shape(config)
    table = entry_cls(HwComponentType.REG, (config.rob_depth,), name, **fields)

    # Powers up with nothing written back and no destination claimed.
    resets = {"wb_fin": 0}
    for atm_operand in rob_dest_operands(config.isa):
        resets[f"active_{atm_operand.name}"] = 0
    return table.reset(**resets)
