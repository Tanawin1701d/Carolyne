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
# The engine threads rob_des_idx / is_spec / spec_tag between stages by
# itself; everything else a later stage or a writeback needs — dest pr_idx
# included — the body carries in the Karray it returns.

from __future__ import annotations

from .atomic_operand import AtomicOperand


class ExecUnitApi:
    """The engine half of a stage body. Subclassed by the O3 generator."""

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

    def zync_with_next_stage(self):
        """The handshake with the next stage's arbiter — the mirror of the
        station-issue zync. The body places it where its own Kathryn
        structure completes a transfer; work outside it does not move the
        µop on."""
        raise NotImplementedError(
            f"{type(self).__name__}.zync_with_next_stage: the generator supplies this")

    def declare_fin(self):
        """This µop is FINISHED — in O3 the engine reports it against the
        threaded rob_des_idx (Rob.on_write_back), which is what lets it
        retire."""
        raise NotImplementedError(
            f"{type(self).__name__}.declare_fin: the generator supplies this")

    def wb_reg(self, atm_opr: AtomicOperand):
        """Write that dest slot back — in O3 the engine drives the class's
        PRF port (and the bypass broadcast) from the slot's own fields of
        the stage's returned record: `pr_idx_<name>` names the register,
        `data_<name>` the value. The body carries both there itself."""
        raise NotImplementedError(
            f"{type(self).__name__}.wb_reg: the generator supplies this")
