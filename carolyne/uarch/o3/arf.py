# Arf — the committed architectural state of ONE register class: one entry per
# architectural register, holding the value that has retired.
#
# `__init__` sets configuration BEFORE calling `super().__init__()`:
# Module.__init__ mints the ident, opens the module scope and runs the @init
# methods, which read that config — leaving it out builds a hollow object whose
# `storage` never exists.
#
# `read` returns a SignalRef (via `to_ref`), not the raw Karray field ref: a
# KarrayRef carries `|=`/`*=` but no arithmetic, so `arf.read(i) + imm` would
# be a TypeError.
#
# Both ports are indexed by a DECODED register number, so a hardwired register
# can only be recognized at RUNTIME. The two halves of uop_contract.md §1.1 are
# not symmetric: the WRITE port only has to know THAT the index is constant, so
# it suppresses the write with one `zif` guard; the READ port has to know WHICH
# constant, so it builds a mux chain, one per entry of `const_regs`. Both
# collapse to nothing when the class declares none.
#
# Consequence of the mux: `read` DECLARES hardware for a class with const
# registers, so it must be called inside an open flow scope, and inside a
# `seq()` the wire is gated on that step's state — read it in the step that
# built it. With no const registers `read` stays a pure expression.
#
# The const entry is still ALLOCATED, not skipped: skipping it would put a hole
# in the array and make every index past it disagree with the architectural
# number.

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
