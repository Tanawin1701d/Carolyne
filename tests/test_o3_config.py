# CPUO3_Config — the ISA plus the numbers the ISA does not decide. The first
# test is the usage documentation; the rest pin the checks.

import pytest

from carolyne.isa import ExecUnit, Uop
from carolyne.isa.riscv import Rv32i, x_file
from carolyne.uarch.o3.config import CPUO3_Config, RsvSpec, RsvType

ISA   = Rv32i()
X     = ISA.reg_file("x")
UNITS = ISA.exec_units                      # every unit RV32I declares


def _cfg(**overrides):
    kwargs = dict(isa=ISA, fe_lanes=2, commit_lanes=2, phy_specs=((X, 64),),
                  rsv_specs=(RsvSpec(True, 16, UNITS, RsvType.RSV_BRANCH),), rob_depth=32,
                  sptag_len=8)
    kwargs.update(overrides)
    return CPUO3_Config(**kwargs)


def test_a_config_is_an_isa_plus_the_machine_knobs():
    cfg = _cfg()
    assert cfg.isa.name == "rv32i"
    # Derived from the ISA — never copied, so it cannot go stale.
    assert cfg.pc_width == 32 and cfg.instr_width == 32
    # Derived from the knobs, the same store-the-count/derive-the-log2 bargain
    # RegFile.amount -> index_width makes.
    assert cfg.rob_idx_width == 5
    # phy_specs read as the map it is: keyed by the RegFile itself.
    assert cfg.phy_size(X) == 64 and cfg.phy_idx_width(X) == 6
    # sptag_len is a WIDTH, not a count — blocks use it as written.
    assert cfg.sptag_len == 8
    # The machine's two widths: how many µops arrive, how many retire. Separate
    # knobs, because a core may retire narrower than it fetches.
    assert cfg.fe_lanes == 2 and cfg.commit_lanes == 2


def test_phy_specs_is_keyed_by_the_reg_file_instance():
    # A dict cannot hold this map — RegFile carries const_regs, so it is
    # unhashable — and identity is the discipline IsaBase already runs on.
    with pytest.raises(TypeError, match="unhashable"):
        {X: 64}
    # Rv32i() shares one RegFile instance by design, so a real twin comes from
    # x_file(), the builder behind it.
    twin = x_file()
    assert twin == X and twin is not X       # value-equal, different instance
    with pytest.raises(ValueError, match="which ISA 'rv32i' does not declare"):
        _cfg(phy_specs=((twin, 64),))


def test_every_renamed_class_needs_a_size():
    # No default: a default is a number nobody chose.
    with pytest.raises(ValueError, match="no physical file size for renamed class"):
        _cfg(phy_specs=())
    with pytest.raises(ValueError, match="sizes class 'x' twice"):
        _cfg(phy_specs=((X, 64), (X, 96)))


def test_rename_must_have_a_spare_physical_register():
    # RV32I's x class is 32 architectural registers; a 32-entry PRF leaves
    # rename nothing to allocate, so it can never make progress.
    with pytest.raises(ValueError, match="leaves no spare for class 'x'"):
        _cfg(phy_specs=((X, 32),))
    assert _cfg(phy_specs=((X, 33),)).phy_idx_width(X) == 6


def test_every_op_the_isa_uses_must_reach_a_station():
    # The machine-level counterpart of IsaBase's unrunnable-µop check: a unit the
    # ISA declares but no station feeds cannot execute anything.
    alu_only = tuple(u for u in UNITS if u.name == "alu")
    with pytest.raises(ValueError, match="no reservation station can issue"):
        _cfg(rsv_specs=(RsvSpec(True, 16, alu_only, RsvType.RSV_EXEC),))
    with pytest.raises(ValueError, match="does not declare"):
        _cfg(rsv_specs=(RsvSpec(True, 16, (ExecUnit("crypto", (Uop("AES", 0),)),),
                                RsvType.RSV_EXEC),))
    with pytest.raises(ValueError, match="nothing can execute"):
        _cfg(rsv_specs=())


def test_a_station_is_checked_on_its_own_terms():
    with pytest.raises(ValueError, match="size must be >= 1"):
        RsvSpec(True, 0, UNITS, RsvType.RSV_BRANCH)
    with pytest.raises(ValueError, match="names no exec unit"):
        RsvSpec(True, 16, (), RsvType.RSV_EXEC)
    with pytest.raises(TypeError, match="issue_o3 must be a bool"):
        RsvSpec(1, 16, UNITS, RsvType.RSV_BRANCH)
    alu_only = tuple(u for u in UNITS if u.name == "alu")
    station  = RsvSpec(False, 8, alu_only, RsvType.RSV_EXEC)
    assert station.label == "alu"
    assert any(u is ISA.uop("ADD") for u in station.uops)


def test_a_station_states_what_kind_it_is():
    # Not derivable from the units: two machines may split one unit set
    # differently, and a station feeding several kinds still has to say which
    # shape its entries have. So it is required, with no default.
    with pytest.raises(TypeError, match="rsv_type must be a RsvType"):
        RsvSpec(True, 16, UNITS, "branch")
    with pytest.raises(TypeError):
        RsvSpec(True, 16, UNITS)                     # nothing to default to


def test_the_kind_decides_the_added_entry_fields():
    pc = ISA.pc_width
    assert RsvSpec(True, 4, UNITS, RsvType.RSV_EXEC).entry_fields(pc) \
        == (("pc", pc),)
    assert RsvSpec(True, 4, UNITS, RsvType.RSV_BRANCH).entry_fields(pc) \
        == (("pc", pc), ("npc", pc))
    # A load/store station is handed no PC: the address is a value it computes.
    assert RsvSpec(True, 4, UNITS, RsvType.RSV_LD_ST).entry_fields(pc) == ()


def test_a_machines_own_entry_fields_are_checked_as_pairs():
    def spec(extra):
        return RsvSpec(True, 16, UNITS, RsvType.RSV_LD_ST, extra_fields=extra)

    assert spec((("lsq_idx", 5),)).extra_fields == (("lsq_idx", 5),)
    assert spec([["lsq_idx", 5]]).extra_fields == (("lsq_idx", 5),)   # normalized

    with pytest.raises(TypeError, match=r"\(name, width\) pairs"):
        spec(("lsq_idx",))
    with pytest.raises(ValueError, match="is not an identifier"):
        spec((("lsq idx", 5),))
    with pytest.raises(TypeError, match="width must be an int"):
        spec((("lsq_idx", "5"),))
    with pytest.raises(ValueError, match="not a legal width"):
        spec((("lsq_idx", 0),))
    with pytest.raises(ValueError, match="two extra fields named 'lsq_idx'"):
        spec((("lsq_idx", 5), ("lsq_idx", 5)))


def test_the_config_is_checked_at_construction():
    with pytest.raises(TypeError, match="isa must be an IsaBase"):
        _cfg(isa="rv32i")
    with pytest.raises(ValueError, match="fe_lanes must be >= 1"):
        _cfg(fe_lanes=0)
    with pytest.raises(TypeError, match="rob_depth must be an int"):
        _cfg(rob_depth=32.0)


def test_a_cycle_cannot_retire_more_than_the_rob_holds():
    _cfg(commit_lanes=4, rob_depth=32)          # a narrow retire is fine
    _cfg(commit_lanes=32, rob_depth=32)         # so is retiring the whole buffer
    with pytest.raises(ValueError, match="commit lanes over"):
        _cfg(commit_lanes=33, rob_depth=32)


def test_the_commit_width_is_held_to_the_same_rules_as_the_others():
    with pytest.raises(ValueError, match="commit_lanes must be >= 1"):
        _cfg(commit_lanes=0)
    with pytest.raises(TypeError, match="commit_lanes must be an int"):
        _cfg(commit_lanes="2")
