# ExecUnitApi — what a stage body reaches the ENGINE through, beside the raw
# Kathryn it now writes (exec_unit.py: a body is natural Kathryn since
# 2026-08-28, the compromise of the no-Kathryn rule). The base declares the
# surface and raises; the O3 generator overrides it with the real machinery
# (uarch/o3/fu.py), one instance per stage invocation, so a call can resolve
# against the stage's own records.
#
# The declare_* calls REGISTER an intent — the engine builds the hardware for
# it against the record the stage RETURNS, which is why a body may call them
# before the value they act on exists in its Python flow.
#
# The body carries everything between stages in the register Karray it
# returns — dest pr_idx and rob_des_idx included — except the
# is_spec/spec_tag pair, which the generator transfers from src to des
# inside zync_with_next_stage.
#
# `get_src` is CONCRETE, not generator-supplied: reading a slot by operand
# is the same under every generator, and the field stem (`data_<name>`,
# uarch/o3/operand_field.py's vocabulary) is written down here once.

from __future__ import annotations

from kathryn.signal import to_ref

from .atomic_operand import AtomicOperand


class ExecUnitApi:
    """The engine half of a stage body. Subclassed by the O3 generator."""

    # --- record reads (concrete) ---------------------------------------------
    def get_src(self, src, atm_opr: AtomicOperand):
        """The value in that source slot: the record's `data_<name>` field.

        An immediate included — an immediate fills a source slot like any
        other, so there is no separate accessor for one."""
        if not atm_opr.is_src:
            raise ValueError(
                f"get_src: operand '{atm_opr.name}' is a {atm_opr.role} — it "
                f"names no source slot to read")
        if not atm_opr.name:
            raise ValueError("get_src: an unnamed operand has no record field")
        return to_ref(getattr(src, f"data_{atm_opr.name}"))

    # --- the engine half (generator-supplied) --------------------------------
    def declare_mis_pred(self, dyn_cond=None):
        """This µop resolved a prediction WRONG when `dyn_cond` holds — the
        engine squashes everything under the µop's tag (its threaded
        is_spec/spec_tag say which). No condition means unconditionally."""
        raise NotImplementedError(
            f"{type(self).__name__}.declare_mis_pred: the generator supplies this")

    def declare_suc_pred(self, dyn_cond=None):
        """This µop resolved a prediction CORRECTLY when `dyn_cond` holds —
        the engine masks the tag out everywhere it is still open."""
        raise NotImplementedError(
            f"{type(self).__name__}.declare_suc_pred: the generator supplies this")

    def zync_with_next_stage(self, src, des):
        """The handshake with the next stage's arbiter — the mirror of the
        station-issue zync, used as a WITH block:

            with api.zync_with_next_stage(src, des):
                ...   # the body's writes to `des` — fire on the grant

        `src` is the record this stage received, `des` the register record
        it hands on; the generator transfers the speculation state AND the
        rob_des_idx from src to des inside the block, so `des` must carry
        all three. The body places the block where its own Kathryn
        structure completes a transfer; work outside it does not move the
        µop on."""
        raise NotImplementedError(
            f"{type(self).__name__}.zync_with_next_stage: the generator supplies this")

    def declare_fin(self, src):
        """This µop is FINISHED — in O3 the engine reports it against the
        `rob_des_idx` carried in `src`, the stage's own record
        (Rob.on_write_back), which is what lets it retire."""
        raise NotImplementedError(
            f"{type(self).__name__}.declare_fin: the generator supplies this")

    def wb_reg(self, atm_opr: AtomicOperand, value):
        """Write `value` back to that dest slot — in O3 the engine drives
        the class's PRF port (and the bypass broadcast) at the slot's
        promised physical register (`pr_idx_<name>`, carried in the
        stage's record). The LAST stage of a unit ends this way: it
        returns None and its results leave through wb_reg.

        RESPECTS THE ENCLOSING KATHRYN SCOPE: a call inside a zif builds a
        gated write — how a body says only SOME of its µops write the slot
        (BrExecUnit's jal/jalr link)."""
        raise NotImplementedError(
            f"{type(self).__name__}.wb_reg: the generator supplies this")
