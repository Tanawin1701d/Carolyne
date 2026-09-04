# The machine's COMMON field names — the fixed-half fields shared across the
# records and the engine's writes: dispatch's promised fields, the stations'
# entries, the api's stage-to-stage transfer. One spelling here, so a record
# and a write keyed on it cannot drift.
#
# A Karray CLASS BODY still names its fields by attribute (`is_spec = kaf(1)`
# — the literal is the name), so the declared records — and ISA-side bodies'
# own records, which may not import uarch — spell the literal; every
# string-keyed WRITE uses these.
#
# `SpecLane` is the one record built out of them: the speculation pair on a
# WIRE, so a prediction resolving in the same cycle can mask it BEFORE the
# clocked write that consumes it. Every place the engine hands the pair from
# one piece of state to another uses it.

from kathryn import Karray, kaf

IS_SPEC     = "is_spec"
SPEC_TAG    = "spec_tag"
ROB_DES_IDX = "rob_des_idx"
UOP_IDX     = "uop_idx"


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
