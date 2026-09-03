# The machine's COMMON field names — the fixed-half fields shared across the
# records and the engine's writes: dispatch's promised fields, the stations'
# entries, the api's stage-to-stage transfer. One spelling here, so a record
# and a write keyed on it cannot drift.
#
# A Karray CLASS BODY still names its fields by attribute (`is_spec = kaf(1)`
# — the literal is the name), so the declared records — and ISA-side bodies'
# own records, which may not import uarch — spell the literal; every
# string-keyed WRITE uses these.

IS_SPEC     = "is_spec"
SPEC_TAG    = "spec_tag"
ROB_DES_IDX = "rob_des_idx"
UOP_IDX     = "uop_idx"
