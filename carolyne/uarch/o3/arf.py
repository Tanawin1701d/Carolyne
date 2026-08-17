# Arf — the committed architectural state of ONE register class: one entry per
# architectural register, holding the value that has retired.
#
# Decisions (2026-08-17):
# - `__init__` sets configuration and then calls `super().__init__()`, in that
#   order. Module.__init__ is what mints the module ident, opens the module
#   scope and RUNS the @init methods, so leaving it out builds a hollow object:
#   com_declare never fires, `storage` never exists, and the failure surfaces at
#   the first read as an AttributeError rather than at construction. Config must
#   still be set first, because com_declare reads it during that same call.
# - `read` returns a SignalRef, not the Karray field ref. A KarrayRef carries
#   `|=`/`*=` and the to_ref hook but NO arithmetic or relational operators, so
#   the raw field works as an assignment source and breaks the moment a caller
#   computes with it (`arf.read(i) + imm` is a TypeError). A method named `read`
#   has to hand back something a datapath can use.
# - It goes through `to_ref` rather than `KarrayRef._to_read_ref()`. Both reach
#   the same node; one is private. If more blocks need this, the right move is
#   for Kathryn to re-export `to_ref` from the package root — it is currently
#   only reachable as `kathryn.signal.to_ref`.
# - Both ports are indexed by a DECODED register number (`dyn_idx`), never by a
#   literal, so a hardwired register can only be recognized at RUNTIME. The write
#   port therefore compares the index against every entry of `const_regs` and
#   suppresses the write when it matches — the "writes are discarded" half of
#   uop_contract.md §1.1, enforced in hardware rather than assumed of the caller.
#   The guard is a `zif` over an AND of `!=` terms, one per const register, and
#   collapses to nothing at all when the class declares none (RV32I's flags-like
#   classes, every x86 class), so an ISA without hardwired registers pays zero.
# - The READ half of §1.1 is a chain of muxes, one per hardwired register, NOT
#   the single `_not_const` guard the write side uses. The two halves are not
#   symmetric: a write only has to know THAT the index is constant, while a read
#   has to know WHICH constant, and each entry of `const_regs` carries its own
#   value. So the guard stays a write-only helper and the read builds per-index
#   equalities instead. Both collapse to nothing when the class declares none.
# - Consequence of the mux: `read` DECLARES hardware for a class with const
#   registers, so it must be called inside an open flow scope, and inside a
#   `seq()` the wire is gated on that step's state — read it in the step that
#   built it. For a class with no const registers `read` stays a pure expression.
# - Together the two halves make this file self-sufficient: x0 reads as 0 and
#   cannot be written, with no reset value and nothing assumed of rename. Rename
#   may still bypass x0 for its own reasons (saving a PRF port); it no longer has
#   to for the architectural state to be right.
# - The const entry is still allocated rather than skipped. Skipping it would
#   put a hole in the array and make every index past it disagree with the
#   architectural number, to save one register.

from kathryn import *
from kathryn.signal import to_ref

from carolyne.isa import RegFile


class ArfEntry(Karray):
    data = kaf()        # no default: the instantiation sizes it from the class


class Arf(Module):

    def __init__(self, isa_reg_file: RegFile):
        # Config first, super() last — see the header.
        self.isa_reg_file = isa_reg_file
        super().__init__()

    @init
    def com_declare(self):
        self.storage = ArfEntry(
            HwComponentType.REG,
            (self.isa_reg_file.amount,),
            "arf" + self.isa_reg_file.name,
            data = self.isa_reg_file.width
        )

    def _not_const(self, dyn_idx):
        """`dyn_idx` names none of the hardwired registers — None if there are
        none to guard against, so the caller emits an unconditional write."""
        guard = None
        for const_idx in sorted(self.isa_reg_file.const_regs):
            term  = (dyn_idx != const_idx)
            guard = term if guard is None else guard.land(term)
        return guard

    def read(self, dyn_idx):
        value = to_ref(self.storage[dyn_idx].data)
        # One mux per hardwired register, because each carries its OWN value —
        # a single not-const guard could not say which constant to return. Reads
        # as an if/elif chain ending in storage, and disappears entirely for a
        # class that declares none.
        for const_idx, const_val in sorted(self.isa_reg_file.const_regs.items()):
            value = mux(dyn_idx == const_idx, const_val, value,
                        name="arf{}_const{}".format(self.isa_reg_file.name, const_idx))
        return value

    def write(self, dyn_idx, data):
        guard = self._not_const(dyn_idx)
        if guard is None:
            self.storage[dyn_idx].data |= data
            return
        with zif(guard):
            self.storage[dyn_idx].data |= data
