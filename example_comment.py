# example_comment — the comment pattern this project writes to, shown as code.
# A reference, not a module: nothing imports it, nothing runs it.
#
#   ~/.claude/skills/codestyle-skill/SKILL.md   rule 7 (comments), 1-9 (layout)
#   CLAUDE.md §7                                what a comment may CONTAIN
#
# Comments stay CORE: what the code does, plus the outside rule a reader would
# break without. Why a design was chosen goes in CLAUDE.md §4.

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Tuple

# Stand-ins so this file resolves on its own. The real ones are in Kathryn and
# in uarch/o3/priority.py. Nothing here is the point; the comments are.
PRI_RENAME = 0


@contextmanager
def priority(_level):
    yield


# =============================================================================
# 1. PLAIN LANGUAGE
# =============================================================================
# Write for a reader whose first language is not English. This rule comes
# first because it applies to every comment in every section below.
#
#   - use the common word, not the clever one
#   - one idea per sentence; do not chain clauses with dashes
#   - no metaphors, and never describe hardware as if it were a person
#
# Domain terms are KEPT: µop, rename, speculation, bypass, writeback, station.
# Those are exact. It is ordinary English that must be plain.
#
#   instead of                        write
#   the value RIDES with the µop      the value is stored in the µop record
#   a µtemp LIVES in one instruction   a µtemp exists only inside one instruction
#   the station OWNS its policy        the station decides its policy
#   a level HANDS a bubble             a level outputs an empty entry
#   an operand REACHES a RegFile       an operand refers to a RegFile
#   the core SPEAKS uop_idx            the core uses uop_idx
#   the BARGAIN this type makes        the rule this type follows
#   the DISCIPLINE the layer runs on   the rule the layer uses
#   it BITES at issue                  it causes a bug at issue
#   a LOAD-BEARING fact                an important fact
#   the cost COMES DUE at x86          the cost appears when x86 is added
#   where the field SITS               where the field is


# =============================================================================
# 2. THE MODULE HEADER
# =============================================================================
# What the module IS, then the one or two rules a reader must know, then a
# TABLE if it has several parts. Never a changelog, never a rationale essay.
#
#   GOOD, and the shape rsv_helper.py uses:
#
#     # Rsv — one reservation station's entry table, built from the ISA
#     # description and the machine's RsvSpec.
#     #
#     # <the rule a reader would break without>
#     #
#     #   src on a register class   valid_<n>  pr_idx_<n>  data_<n>
#     #   src on a µtemp only       data_<n>
#     #
#     # The PC is NOT in the base. Which stations carry one depends on the
#     # KIND of station, so pc/npc are added by RsvSpec.entry_fields().
#
#   BAD — history, and a decision that belongs in the design log:
#
#     # Decisions (2026-08-19): we first derived the port shape from the µops
#     # and reverted it, because deriving made a unit's shape depend on which
#     # mops happened to exist. Declaring is cheaper to reason about and the
#     # cost is that every construction site names its slots, which we accept.


# =============================================================================
# 3. SECTION SEPARATORS
# =============================================================================
# Dashed lines divide logical groups. Short groups inline, long files in a
# full-width block like the two above. Adapt the comment char per language.

# --- reads -------------------------------------------------------------------


@dataclass(frozen=True)
class WakeSlot:
    """One source slot a station waits for."""

    name   : str                     # the stem of every field built for it
    width  : int                     # bits; 0 = nothing to store, field dropped
    pr_idx : Optional[int] = None    # physical register; None on a µtemp

    # Rule 2: a body that fits on one line stays there, and a group of them
    # aligns its return types and bodies into a column.
    @property
    def is_arch  (self) -> bool: return self.pr_idx is not None
    @property
    def is_stored(self) -> bool: return self.width > 0


# =============================================================================
# 4. THE DOCSTRING — SIZED TO THE CODE
# =============================================================================
# ONE summary line, then short `-` bullets. Never a paragraph.
#
# THE DOC IS NEVER LONGER THAN THE BODY IT DESCRIBES. A bullet is not free. It
# is worth including only when it states a rule the reader would break without
# it — the WHY, not the WHAT. Most short methods have no such rule, so most
# short methods get one line and stop.
#
#   body            doc
#   1-2 lines       the name alone, or one line if it is not obvious
#   3-8 lines       one line; add ONE bullet only if a rule outside the file
#                   applies
#   longer          summary + bullets, one per rule, still no paragraph
#
# If the bullets outnumber the statements, the doc is wrong. Either cut it, or
# the method is doing too much.
#
# ONE EXCEPTION: an abstract method whose body is a stub. There the docstring
# IS the deliverable, because it is the contract someone writes an
# implementation against, so the size rule does not apply. See
# isa/exec_unit_api.py.


def wake_bit(slot: WakeSlot, bit: int) -> int:
    """The mask bit this slot contributes."""
    return (1 << bit) if slot.is_arch else 0


def build_wake_mask(slots: Tuple[WakeSlot, ...], active: int) -> int:
    """The slots an entry waits for, as a bit mask.

    - an INACTIVE slot has no value to wait for, so it is not in the mask: the
      record has one group per operand the ISA declares, and a µop fills only
      some of them
    """
    mask = 0
    for bit, slot in enumerate(slots):
        if slot.is_arch and (active >> bit) & 1:
            mask |= 1 << bit
    return mask


def build_wake_mask_BAD(slots, active):
    """
    Builds a wake mask. Originally took every operand, but µtemps never issued,
    so we gate here; the cost is one AND per slot, which we judged acceptable.
    """                                    # paragraph + history + cost/benefit
    mask = 0
    for bit, slot in enumerate(slots):     # bit is the bit
        if slot.is_arch and (active >> bit) & 1:
            mask |= 1 << bit               # set the bit
    return mask


# =============================================================================
# 5. THE CAPS MARKERS
# =============================================================================
# Important facts go in CAPS so they are easy to see when skimming. Three are
# greppable and mean specific things. Use them and nothing else:
#
#   LIMIT:     known incompleteness that is CORRECT to ship right now
#   TODO:      planned work, greppable, written so a stranger could do it
#   NOT here:  a deliberate absence, so nobody "fixes" it by adding the thing
#
# A marker is a bullet and follows the same rule. It goes in because the next
# reader would waste time without it, not to show that the author thought
# about it.
#
# Bare CAPS inside a sentence mark the important word: "the field is
# AUTHORITATIVE", "a µtemp destination RAISES". Use this rarely. If everything
# is emphasised, nothing is.


def issue_one(slots: Tuple[WakeSlot, ...], ready: int) -> Optional[int]:
    """The slot that issues this cycle, or None.

    - NOT here: the age track. That belongs to an out-of-order station
    """
    for bit, _slot in enumerate(slots):
        if (ready >> bit) & 1:
            return bit
    return None


# =============================================================================
# 6. INLINE COMMENTS
# =============================================================================
# Say WHY. The code already says what, so never restate a line that reads
# itself. But DO annotate what does not: a long stretch, a dense expression, or
# code whose reason is outside the file gets exactly ONE line.
#
#   trailing         on the one line it explains, when it fits the margin
#   dedicated line   above the block, when the note covers several lines
#
# One line, not two. If it needs a paragraph, the code needs a helper with a
# name instead.


def sign_extend(value: int, from_bit: int) -> int:
    """Sign-extend `value`, treating `from_bit` as its sign."""
    m = 1 << from_bit
    return (value ^ m) - m                  # flip-and-subtract, no fill-bit mux


def route_lane(lane: int, station_ids: Tuple[int, ...]) -> int:
    """The station this lane sends to."""
    # modulo the LANE: fixed at elaboration, so routing costs no hardware
    return station_ids[lane % len(station_ids)]


def build_ready(valid: int, active: int, slot_cnt: int) -> int:
    """Whether every slot this entry waits for has landed."""
    ready = 1
    for bit in range(slot_cnt):
        landed = (valid  >> bit) & 1
        wanted = (active >> bit) & 1
        # an unfilled slot has no value to wait for, so it must not block issue
        ready &= landed | (wanted ^ 1)
    return ready


def write_entry_GOOD(table, row_idx: int, fields: dict) -> None:
    """Copy a row, then overlay the rename half."""
    table[row_idx] |= fields                # fresh selection: |= rebinds the name

    # at EQUAL priority a zif write is emitted BEFORE an unconditional one, so
    # an overlay written plainly builds the opposite hardware, with no error
    with priority(PRI_RENAME):
        table[row_idx] |= {"is_spec": 1}


def write_entry_BAD(table, row_idx: int, fields: dict) -> None:
    # write the fields to the table                  <- restates the code
    table[row_idx] |= fields
    # set is_spec to 1                               <- restates the code
    with priority(PRI_RENAME):                       # use priority
        table[row_idx] |= {"is_spec": 1}


# =============================================================================
# 7. ALIGNMENT (rules 1 and 8) — a comment pass keeps these intact
# =============================================================================


def build_station(
    config    : dict,
    rsv_spec  : dict,
    name      : str = "",
    rsv_idx   : int = 0,
) -> dict:
    """Assemble one station. Signature: one param per line at 3+, `:` aligned."""
    # Grouped assignments align the `=`; dict literals align the `:`.
    size      = rsv_spec["size"]
    units     = rsv_spec["exec_unit"]
    entry_cnt = size * len(units)

    promised = {"rob_des_idx": rsv_idx,
                "is_spec"    : 0,
                "spec_tag"   : 0}

    # Parallel calls on sibling objects align the dot, so the group reads as a
    # table and a missing or duplicated call is easy to see.
    config["fetch"]   .update(promised)
    config["decode"]  .update(promised)
    config["dispatch"].update(promised)

    return {"size": size, "entry_cnt": entry_cnt}


# =============================================================================
# 8. WHAT NEVER APPEARS IN SOURCE
# =============================================================================
#   - dates, authorship, "changed by", "as of 2026-09-05"
#   - "this was tried and reverted", "we considered X but chose Y"
#   - cost/benefit prose, alternatives weighed, rationale essays
#   - commented-out code (git already stores it)
#   - restating the line below in English
#
# The first three are real and worth keeping. They go in CLAUDE.md §4, which is
# the design log. A comment that starts "Decision:" is in the wrong file. On
# 2026-08-19 those blocks were removed from every file under carolyne/, −948
# lines. A revision pass must not add them back.
