# The hardware fields one µop operand contributes to a record — named and sized
# in ONE place.
#
# Both the reservation station and the reorder buffer carry a group of fields
# per operand, and what differs between them is only WHICH kinds each keeps,
# never what a kind is called or how wide it is:
#
#   active_<n>       1   this µop really fills/writes that slot
#   valid_<n>        1   a source's value has landed and the entry may issue
#   wb_required_<n>  1   the WRITEBACK must land before the instruction
#                        retires — DEST_W_REQ cores only, dropped elsewhere
#   data_<n>         w   the value itself, the class width or the µtemp's
#   pr_idx_<n>       w   the physical register rename gave it
#   ar_idx_<n>       w   the architectural register it belongs to
#
# That listing IS the order a group is built in (KIND_ORDER): a caller states
# WHICH kinds its record keeps, never in what order they land.
#
# A caller names the kinds its record carries and this module answers with the
# field names and widths, so two records cannot drift apart or disagree about a
# spelling. `where` names the caller for the error messages, the way
# check_matcher_pair does in the ISA layer.

from kathryn import kaf

from carolyne.isa import AtomicOperand, IsaBase
from carolyne.uarch.o3.config import CPUO3_Config

ACTIVE      = "active"
VALID       = "valid"
WB_REQUIRED = "wb_required"
DATA        = "data"
PR_IDX      = "pr_idx"
AR_IDX      = "ar_idx"

# The ONE order a group's fields are built in, whatever order a caller lists
# them: the status bits, then the value, then the indexes. Every record here
# keeps only SOME of the kinds, so this is what makes their groups read the
# same way — src_1's fields in a station line up with src_1's in the ROB.
KIND_ORDER = (ACTIVE, VALID, WB_REQUIRED, DATA, PR_IDX, AR_IDX)

# The kinds that name a REGISTER, and therefore need an architectural class.
_INDEX_KINDS = (PR_IDX, AR_IDX)
# The kinds that are one bit of state about the operand.
_FLAG_KINDS  = (VALID, WB_REQUIRED, ACTIVE)


def field_name(kind: str, atm_operand: AtomicOperand) -> str:
    """The one spelling of a field: the kind, then the operand's own name."""
    return f"{kind}_{atm_operand.name}"


def require_named(atm_operand: AtomicOperand, where: str) -> str:
    """An operand's name, refusing the ones that have none.

    The name is the stem of every field built for that operand, so a core
    without one cannot be turned into hardware at all.
    """
    if not atm_operand.name:
        raise ValueError(
            f"{where}: a {atm_operand.role} operand core has no name, so its fields "
            f"cannot be named — name the cores the ISA declares")
    return atm_operand.name


def named_atomic_operands(isa: IsaBase, where: str) -> tuple:
    """Every atomic operand the ISA's µops fill, sources then destinations.

    Core-wide, which is what a record built before a µop is routed needs: it
    has to hold whatever the µop turns out to be. Deduped by identity already
    (IsaBase does it), and held to non-empty names here, since a name is the
    stem of every field built for the operand.
    """
    srcs, dests = [], []
    for atm_operand in isa.used_atomic_operands():
        require_named(atm_operand, where)
        (srcs if atm_operand.is_src else dests).append(atm_operand)
    return tuple(srcs) + tuple(dests)


def operand_fields(config      : CPUO3_Config,
                   atm_operand : AtomicOperand,
                   kinds       : tuple,
                   where       : str) -> dict:
    """The named, sized kaf() specs these kinds contribute for one operand.

    Built in KIND_ORDER, not in the order the caller listed them, so one
    operand's group reads the same in every record that keeps it.

    A kind whose width works out to zero contributes NOTHING: that is `ar_idx`
    on a one-register class, where there is no index to choose and a 0-bit
    field is not a legal width.
    """
    require_named(atm_operand, where)

    fields = {}
    for kind in in_record_order(kinds, where):
        width = field_width(config, atm_operand, kind, where)
        if width:
            fields[field_name(kind, atm_operand)] = kaf(width)
    return fields


def in_record_order(kinds: tuple, where: str) -> tuple:
    """The kinds a caller asked for, sorted into the order a record holds them.

    Also what refuses a kind that does not exist, before anything is sized.
    """
    for kind in kinds:
        if kind not in KIND_ORDER:
            raise ValueError(f"{where}: no such operand field kind '{kind}'")
    return tuple(kind for kind in KIND_ORDER if kind in kinds)


def field_width(config      : CPUO3_Config,
                atm_operand : AtomicOperand,
                kind        : str,
                where       : str) -> int:
    """How wide one kind is for this operand. Zero means "nothing to store"."""
    if kind == WB_REQUIRED and not atm_operand.is_write_required:
        # only a DEST_W_REQ core stores the bit: everywhere else the role
        # itself is the constant answer, and a constant needs no storage
        return 0
    if kind in _FLAG_KINDS:
        return 1

    if kind == DATA:
        return (atm_operand.reg_file.width if atm_operand.has_arch
                else atm_operand.intermediate.width)

    if kind not in _INDEX_KINDS:
        raise ValueError(f"{where}: no such operand field kind '{kind}'")

    # An index names a register OF A CLASS, which a µtemp has not got: it is
    # one value node, dead at the instruction boundary.
    if not atm_operand.has_arch:
        raise ValueError(
            f"{where}: operand '{atm_operand.name}' targets a µtemp only, so it has "
            f"no {kind} — a µtemp names no register of any class")

    if kind == PR_IDX:
        return config.phy_idx_width(atm_operand.reg_file)
    return atm_operand.reg_file.index_width      # 0 on a one-register class
