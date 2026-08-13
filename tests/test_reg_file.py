# RegFile metadata: index_width derivation, validation guards, and the two
# instantiations the first paper targets (RV32I x-file, mini-x86 gpr+flags).

import pytest

from carolyne.isa import RegFile


def test_index_width_derived_from_amount():
    assert RegFile("x",     32, 32).index_width == 5   # RV32I
    assert RegFile("gpr",   32,  8).index_width == 3   # mini-x86
    assert RegFile("flags",  6,  1).index_width == 0   # single reg -> no index
    assert RegFile("odd",   16,  3).index_width == 2   # non-power-of-two rounds up


def test_rv32i_x_file():
    x = RegFile("x", 32, 32, const_regs={0: 0})        # x0 hardwired to zero
    assert x.is_const(0) and not x.is_const(1)
    assert x.renamed


def test_validation_guards():
    with pytest.raises(ValueError):
        RegFile("", 32, 32)                            # empty name
    with pytest.raises(ValueError):
        RegFile("x", 0, 32)                            # zero width
    with pytest.raises(ValueError):
        RegFile("x", 32, 0)                            # zero amount
    with pytest.raises(ValueError):
        RegFile("x", 32, 32, const_regs={32: 0})       # const idx out of range
    with pytest.raises(ValueError):
        RegFile("x", 4, 32, const_regs={0: 16})        # const value overflows width
