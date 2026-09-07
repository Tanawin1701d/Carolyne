# THE record-field vocabulary of the O3 core: every field name, spelled once.
#
# A name is written down here and nowhere else, so a record and a write keyed
# on it cannot disagree and a typo in one of them cannot pass silently.
#
# Two kinds of name:
#   WHOLE FIELD   the field is called this (`pc`, `wb_fin`, `rsv_id`)
#   OPERAND STEM  the field is this plus an operand's own name, built by
#                 operand_field.field_name(): VALID + "src_1" -> `valid_src_1`
# Some words are both: a station entry has its own `valid` bit AND a
# `valid_src_1` per source. One word, one constant, both uses.
#
# LIMIT: a Karray CLASS BODY names its fields by ATTRIBUTE (`is_spec = kaf(1)`
# — the literal IS the name), so a declaration cannot use a constant. Every
# string-keyed WRITE and getattr() read uses these, and
# tests/test_common_field.py holds the declarations to them, which is what
# closes the gap the class bodies leave.
#
# ISA-side records spell their own literals: isa/ may not import uarch.
#
# `SpecLane` is the one record built out of them: the speculation pair on a
# WIRE, so a prediction resolving in the same cycle can mask it BEFORE the
# clocked write that consumes it.

from kathryn import Karray, kaf

# --- the machine's fixed half, carried by several records --------------------
VALID       = "valid"           # the row holds something this cycle
PC          = "pc"
NPC         = "npc"
UOP_IDX     = "uop_idx"         # WHICH µop of the ISA's vocabulary
IS_BRANCH   = "is_branch"       # the ROB's two commit barriers
IS_STORE    = "is_store"
RSV_ID      = "rsv_id"          # which station a dispatch lane is aimed at
IS_SPEC     = "is_spec"         # under an open speculation; spec_tag says which
SPEC_TAG    = "spec_tag"
ROB_DES_IDX = "rob_des_idx"     # the ROB entry a µop belongs to

# --- one record each ---------------------------------------------------------
INSTR          = "instr"            # fetch: the encoded word, the ONE raw-bits field
WB_FIN         = "wb_fin"           # rob:   the writeback has landed
TRACK          = "track"            # rsv:   an out-of-order station's age order
IS_LOWER_TRACK = "is_lower_track"
BUSY           = "busy"             # store_buf: holds a store not yet in memory
COMPLETE       = "complete"         # store_buf: the ROB retired it
MEM_ADDR       = "mem_addr"
FIN            = "fin"              # prf:   the physical register was written back
RENAMED        = "renamed"          # rt:    this arch register is renamed
PRF_IDX        = "prf_idx"
FIX_TAG        = "fix_tag"          # mpft:  the mask a squash kills with

# --- fold EXTRAS: names a reduce tree hangs on its intermediate view ----------
# Not record fields. A fold carries its partial answers up the tree in named
# slots, and the producer and the reader must agree on the name.
NODE_IDX        = "idx"               # rsv_o3: this node's winning row, binary
NODE_READY      = "ready"             # rsv_o3: anything ready under this node
ENTRY_READY     = "entry_ready"       # rsv_o3: the same two, as leaf extras
ENTRY_IDX       = "entry_idx"
SEARCH_HIT      = "search_hit"        # store_buf: a match under this node
SEARCH_PRE_WRAP = "search_pre_wrap"   # store_buf: which side of the wrap

# --- operand STEMS: these combine with an operand name -----------------------
# operand_field.field_name() joins them; the sizing rules are that module's.
ACTIVE      = "active"          # this µop fills/writes that slot
WB_REQUIRED = "wb_required"     # the writeback must land before retirement
DATA        = "data"            # the value itself; also a whole field on
                                # prf/arf/store_buf. isa/exec_unit_api.py
                                # restates this stem in get_src (isa may not
                                # import uarch), so a rename here renames there
PR_IDX      = "pr_idx"
AR_IDX      = "ar_idx"


class SpecLane(Karray):
    """The speculation pair in flight, on a wire.

    A register only clears at the edge, so a value copied out of one in the
    resolve cycle carries a tag already resolved. Routing it through a lane
    gives `on_suc_pred` somewhere to mask it first: the producer drives the
    lane, the resolve overrides it at PRI_SUC_PRED, and the consumer reads
    the lane instead of the register.

    Used by the store buffer's push and the exec complex's stage hop; the
    station's `issue_lane` is the same idea on a whole entry record.

    `spec_tag` is sized at the call site — sptag_len is a config fact.
    """
    is_spec  = kaf(1)
    spec_tag = kaf()
