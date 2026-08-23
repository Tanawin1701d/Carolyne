# IsaBase — the container a generator is handed: the ISA's register classes,
# its µop templates, the machine's exec units, and the mops binding encodings
# to µop sequences. The first test is the usage documentation (a
# two-instruction toy ISA); the rest pin the cross-checks that make the
# container worth having — notably "a mop names a µop the ISA never declared",
# which is the validation that went missing when Uop dropped its `unit` field.

import pytest

from carolyne.isa import (
    AtomicOperand, ExecUnit, FieldRef, InstrFieldMatch, IsaBase, Mop,
    Operand, OperandRole, RegFile, TargetKind, Uop, UopSeq,
)

SRC, DEST  = OperandRole.SRC, OperandRole.DEST
ARCH, TEMP = TargetKind.ARCH, TargetKind.TEMP

X     = RegFile("x", 32, 32, const_regs={0: 0})
FLAGS = RegFile("flags", 6, 1)

# The cores are SHARED constants, the way a per-ISA package shares them: a unit
# declares the slots it has, and IsaBase holds every µop to that declaration —
# which it can only do if the µop names the same instances.
AOPR_SRC   = AtomicOperand(SRC,  "src_1",  reg_file=X)
AOPR_SRC_2 = AtomicOperand(SRC,  "src_2",  reg_file=X)   # declared, never filled
AOPR_DEST  = AtomicOperand(DEST, "dest_1", reg_file=X)

def _uop(name, reg_file=X):
    """One µop template of the toy ISA — the shape both instructions share."""
    src  = AOPR_SRC  if reg_file is X else AtomicOperand(SRC,  reg_file=reg_file)
    dest = AOPR_DEST if reg_file is X else AtomicOperand(DEST, reg_file=reg_file)
    return Uop(name,
               srcs=(Operand(src, ARCH, FieldRef("rs1")),),
               dests=(Operand(dest, ARCH, FieldRef("rd")),))


# The templates are shared constants too: a unit lists the very instances the
# mops name, which is what identity membership means.
ADD  = _uop("ADD")
LOAD = _uop("LOAD")

ALU = ExecUnit("alu", (ADD,),  src_operands=(AOPR_SRC,), dest_operands=(AOPR_DEST,))
MEM = ExecUnit("mem", (LOAD,), src_operands=(AOPR_SRC,), dest_operands=(AOPR_DEST,))


def _mop(uop, opcode):
    # One encoding → one µop sequence. (Field binding is still preliminary:
    # the matcher is a single InstrFieldMatch on the opcode bits.)
    return Mop(matcher_field=InstrFieldMatch("opcode", ((0, 7),)),
               uop_seq=(UopSeq(uops=(uop,), matcher_field=InstrFieldMatch(opcode, ((0, 7),))),))


def _walk(mops):
    """The uops/operands/cores a set of mops actually uses, in order.

    A real package declares these from its own module constants (see
    riscv/rv32i.py); this toy builds its shapes inside _mop, so the default
    declaration is read back off the mops. Tests that pin the cross-checks
    override one vocabulary with something the mops do not use.
    """
    uops     = tuple(u for mop in mops for seq in mop.uop_seq for u in seq.uops)
    operands = tuple(o for u in uops for o in u.srcs + u.dests)
    # Deduped by identity: shared constants are declared ONCE, which is the
    # shape a real package has (riscv/rv32i.py) and what IsaBase demands.
    return uops, operands, _once(o.atomic for o in operands)


def _once(items):
    seen = {}
    for item in items:
        seen.setdefault(id(item), item)
    return tuple(seen.values())


def _isa(**overrides):
    mops = overrides.pop("mops", (_mop(ADD, "add"), _mop(LOAD, "lw")))
    uops, operands, cores = _walk(mops)
    kwargs = dict(name="toy", pc_width=32, pc_align=4, ilen_bytes=4,
                  reg_files=(X,), atomic_operands=cores,
                  operands=operands, exec_units=(ALU, MEM),
                  uops=uops, mops=mops)
    kwargs.update(overrides)
    return IsaBase(**kwargs)


def test_isa_holds_the_vocabularies():
    isa = _isa()
    assert isa.uop("ADD") is ADD and isa.unit("mem") is MEM
    assert isa.reg_file("x") is X
    assert isa.used_uops() == (ADD, LOAD)
    assert isa.used_reg_files() == (X,)
    # Two mops, one µop each, two operands per µop, one core per operand.
    assert len(isa.used_uops()) == 2
    # Four slots, but the two mops SHARE the cores under them — which is what
    # lets a unit declare the slots it has.
    assert len(isa.used_operands()) == 4 and len(isa.used_atomic_operands()) == 2
    # Routing is read out of the unit set, not stamped into the µops.
    assert isa.units_for(ADD) == (ALU,)
    with pytest.raises(ValueError):
        isa.uop("ADQ")                      # unknown name fails loudly
    with pytest.raises(ValueError):
        isa.unit("crypto")
    with pytest.raises(ValueError):
        isa.reg_file("gpr")


def test_it_carries_how_instruction_addresses_work():
    # The PC is not a register class (§4.3) but it still has a width, and the
    # engine cannot size fetch, the redirect path or the ROB's pc without it.
    isa = _isa()
    assert (isa.pc_width, isa.pc_align, isa.ilen_bytes) == (32, 4, 4)
    # Derived, not declared — the always-zero low bits of any instruction
    # address, which is what lets a stored PC be narrowed.
    assert isa.pc_align_bits == 2
    # A byte-aligned ISA drops nothing.
    assert _isa(pc_align=1, ilen_bytes=1).pc_align_bits == 0


def test_the_addressing_scalars_are_held_to_each_other():
    # What three loose ints could not check alone.
    with pytest.raises(ValueError, match="power of two"):
        _isa(pc_align=3)
    with pytest.raises(ValueError, match="not a multiple"):
        _isa(pc_align=4, ilen_bytes=2)      # stepping by 2 leaves a 4-aligned pc misaligned
    with pytest.raises(ValueError, match="cannot address past"):
        _isa(pc_width=2, pc_align=4)
    for bad in (dict(pc_width=0), dict(pc_align=0), dict(ilen_bytes=0)):
        with pytest.raises(ValueError, match=">= 1"):
            _isa(**bad)
    with pytest.raises(TypeError):
        _isa(ilen_bytes="4")                # a string is not a length
    with pytest.raises(TypeError):
        _isa(pc_width=True)                 # nor is a bool a width


def test_a_uop_may_be_claimed_by_several_units():
    # Two ALUs is a machine-configuration choice, not a description error:
    # the elaborator picks which one issues a given µop.
    alu2 = ExecUnit("alu2", (ADD,), src_operands=(AOPR_SRC,),
                    dest_operands=(AOPR_DEST,))
    isa  = _isa(exec_units=(ALU, alu2, MEM))
    assert [u.name for u in isa.units_for(ADD)] == ["alu", "alu2"]


def test_a_mop_may_not_target_an_undeclared_reg_file():
    # Same rule for register classes: the elaborator sizes one PRF/RAT per
    # declared file, so a class only some crack knows about would be missed.
    with pytest.raises(ValueError, match="register file 'flags'"):
        _isa(mops=(_mop(_uop("ADD", reg_file=FLAGS), "add"),))


def test_a_mop_may_not_use_an_undeclared_uop():
    # The chain is checked one link at a time: a µop riding inside a mop is
    # not thereby part of the ISA — and an equal-but-separate template is a
    # DIFFERENT µop, since these match by identity.
    with pytest.raises(ValueError, match="does not declare in uops"):
        _isa(uops=(_uop("ADD"),))


def test_a_mop_may_not_use_an_undeclared_operand_or_core():
    core  = AtomicOperand(SRC, reg_file=X)
    spare = Operand(core, ARCH, FieldRef("rs1"))
    with pytest.raises(ValueError, match="does not declare in operands"):
        _isa(operands=(spare,))
    with pytest.raises(ValueError, match="does not declare in atomic_operands"):
        _isa(atomic_operands=(core,))


def test_operands_are_matched_by_identity_not_equality():
    # An equal-but-separate rule is what the identity match exists to catch:
    # a package shares operand constants so every template naming rs1 names
    # ONE object, and a crack that quietly rebuilt it has drifted.
    mops = (_mop(ADD, "add"),)
    _, operands, _ = _walk(mops)
    twin = Operand(operands[0].atomic, operands[0].target_kind,
                   operands[0].index, operands[0].matcher)

    assert twin == operands[0] and twin is not operands[0]
    with pytest.raises(ValueError, match="does not declare in operands"):
        _isa(mops=mops, operands=(twin,) + operands[1:])


def test_a_vocabulary_may_not_list_one_instance_twice():
    # Cores and operands have no name to key on, so a duplicate is the same
    # object listed twice; µops are caught by their name, which is the same
    # bug read the other way round.
    mops = (_mop(ADD, "add"),)
    uops, operands, cores = _walk(mops)
    with pytest.raises(ValueError, match="same object twice"):
        _isa(mops=mops, operands=operands + operands)
    with pytest.raises(ValueError, match="duplicate uops name"):
        _isa(mops=mops, uops=uops + uops)
    # ...while value-equal twins are two legitimate slots.
    assert _isa(mops=mops, atomic_operands=cores + (AtomicOperand(SRC, reg_file=X),))


def test_reg_files_are_matched_by_identity():
    # An equal-but-different RegFile is a *second* class to the elaborator,
    # so declaring a twin does not satisfy the check.
    twin = RegFile("x", 32, 32, const_regs={0: 0})
    assert twin == X                        # value-equal...
    with pytest.raises(ValueError, match="does not declare"):
        _isa(reg_files=(twin,))             # ...but not the instance the µops target


def test_every_declared_uop_needs_a_unit_that_executes_it():
    with pytest.raises(ValueError, match="no exec unit executes"):
        _isa(exec_units=(ALU,))             # nothing runs LOAD


def test_a_unit_may_list_uops_this_isa_never_uses():
    # The reverse direction is allowed on purpose, so one ExecUnit definition
    # can be shared across ISAs.
    big_alu = ExecUnit("alu", (ADD, _uop("SUB"), _uop("XOR")),
                       src_operands=(AOPR_SRC,), dest_operands=(AOPR_DEST,))
    isa = _isa(exec_units=(big_alu, MEM))
    assert isa.used_uops() == (ADD, LOAD)


def test_declared_but_unused_reg_file_is_fine():
    # x86 FLAGS declared before any crack writes it, say — declaring more
    # than the mops use is not an error, the reverse is.
    isa = _isa(reg_files=(X, FLAGS))
    assert isa.reg_file("flags") is FLAGS and isa.used_reg_files() == (X,)


def test_declared_but_unused_operands_and_uops_are_fine_too():
    # Same direction as the reg-file rule: a package may write a rule down
    # before a crack uses it.
    mops = (_mop(ADD, "add"),)
    uops, operands, cores = _walk(mops)
    spare_core = AtomicOperand(DEST, reg_file=FLAGS)
    isa = _isa(mops=mops,
               atomic_operands=cores + (spare_core,),
               operands=operands + (Operand(spare_core, ARCH),),
               uops=uops + (LOAD,))          # declared, no mop reaches it
    assert len(isa.uops) == len(isa.used_uops()) + 1
    assert len(isa.operands) == len(isa.used_operands()) + 1


def test_isa_validation():
    with pytest.raises(ValueError):
        _isa(name="")                       # unnamed ISA
    with pytest.raises(ValueError):
        _isa(mops=())                       # empty vocabulary
    with pytest.raises(ValueError):
        _isa(reg_files=())
    with pytest.raises(TypeError):
        _isa(uops=(ADD, "LOAD"))            # a string is not a Uop
    with pytest.raises(TypeError):
        _isa(reg_files=(X, "flags"))
    with pytest.raises(ValueError, match="duplicate"):
        _isa(exec_units=(ALU, ExecUnit("alu", (LOAD,))))
    with pytest.raises(ValueError, match="duplicate"):
        _isa(reg_files=(X, RegFile("x", 8, 4)))


def test_a_per_isa_package_may_subclass_it():
    # IsaBase is a base: a package with extra description fields subclasses
    # it (staying frozen, staying data), otherwise a factory returning
    # IsaBase is the plain way.  See the isa.py header.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class ToyIsa(IsaBase):
        prefixes : tuple = ()

    mops = (_mop(ADD, "add"), _mop(LOAD, "lw"))
    uops, operands, cores = _walk(mops)
    addr = dict(pc_width=32, pc_align=4, ilen_bytes=4)
    isa = ToyIsa(name="toy", **addr, reg_files=(X,), atomic_operands=cores,
                 operands=operands, exec_units=(ALU, MEM),
                 uops=uops, mops=mops, prefixes=("0x66",))
    assert isa.prefixes == ("0x66",) and isa.uop("ADD") is ADD
    with pytest.raises(ValueError):         # inherited checks still run
        ToyIsa(name="", **addr, reg_files=(X,), atomic_operands=cores, operands=operands,
               exec_units=(ALU,), uops=uops, mops=mops)


def test_it_reads_the_operand_cores_that_reach_one_exec_unit():
    # units_for() walked the other way, in two halves: the elaborator building
    # the ALU sizes its read ports off the srcs and its write ports off the
    # dests, so the query never makes it re-split a mixed tuple.
    isa     = _isa()
    add_uop = isa.mops[0].uop_seq[0].uops[0]

    srcs  = isa.src_atomic_operands_for(ALU)
    dests = isa.dest_atomic_operands_for(ALU)
    assert [c.role for c in srcs]  == [SRC]
    assert [c.role for c in dests] == [DEST]
    # The ADD µop's slots and only those, BY IDENTITY — the LOAD µop's cores
    # belong to mem, even though every core in this toy is value-equal.
    assert [id(c) for c in srcs]  == [id(add_uop.srcs[0].atomic)]
    assert [id(c) for c in dests] == [id(add_uop.dests[0].atomic)]


def test_the_two_halves_are_disjoint():
    # Role lives in the core and Uop cross-checks it against slot position,
    # so nothing can land in both halves.
    isa = _isa()
    for unit in isa.exec_units:
        srcs  = {id(c) for c in isa.src_atomic_operands_for(unit)}
        dests = {id(c) for c in isa.dest_atomic_operands_for(unit)}
        assert not srcs & dests


def test_a_units_port_shape_is_what_it_declares():
    # DECLARED, not derived from the µops that happen to reach it: a port shape
    # is a fact about the unit, and deriving it would make it depend on which
    # mops exist. A unit that declares slots no instruction uses keeps them —
    # that is the ISA saying the port is there.
    wide = ExecUnit("alu", (ADD,), src_operands=(AOPR_SRC, AOPR_SRC_2),
                    dest_operands=(AOPR_DEST,))
    isa  = _isa(exec_units=(wide, MEM),
                atomic_operands=(AOPR_SRC, AOPR_SRC_2, AOPR_DEST))

    assert isa.src_atomic_operands_for(wide) == (AOPR_SRC, AOPR_SRC_2)
    assert AOPR_SRC_2 not in isa.used_atomic_operands()   # no µop fills it


def test_a_unit_that_runs_nothing_the_mops_reach_has_no_cores():
    # Declared-but-unused units stay legal, so the empty tuple is an answer,
    # not an error (same rule as test_a_unit_may_list_uops_this_isa_never_uses).
    isa = _isa()
    fpu = ExecUnit("fpu", (_uop("FADD"),))
    assert isa.src_atomic_operands_for(fpu)  == ()
    assert isa.dest_atomic_operands_for(fpu) == ()


def test_the_unit_query_wants_a_unit_not_its_name():
    isa = _isa()
    with pytest.raises(TypeError, match="self.unit"):
        isa.src_atomic_operands_for("alu")
    with pytest.raises(TypeError, match="self.unit"):
        isa.dest_atomic_operands_for("alu")


def test_a_uop_may_not_ask_a_unit_for_a_slot_it_has_not_got():
    # The check the declared port shape buys: an instruction that fills a slot
    # its unit never declared would size a read port that does not exist.
    narrow = ExecUnit("alu", (ADD,), dest_operands=(AOPR_DEST,))   # no sources
    with pytest.raises(ValueError, match="does not declare"):
        _isa(exec_units=(narrow, MEM))


def test_every_unit_claiming_a_uop_must_cover_it():
    # Which unit issues a µop is the elaborator's routing choice, so the µop
    # has to run on ANY unit listing it — not merely on one of them.
    covered   = ExecUnit("alu",  (ADD,), src_operands=(AOPR_SRC,),
                         dest_operands=(AOPR_DEST,))
    uncovered = ExecUnit("alu2", (ADD,), dest_operands=(AOPR_DEST,))
    with pytest.raises(ValueError, match="'alu2' does not declare"):
        _isa(exec_units=(covered, uncovered, MEM))


def test_a_unit_states_the_direction_of_each_slot():
    # A source slot is one the unit READS; putting a destination there is a
    # description error, not a shape the elaborator should try to build.
    with pytest.raises(ValueError, match="those are the slots the unit reads"):
        ExecUnit("alu", (ADD,), src_operands=(AOPR_DEST,))
    with pytest.raises(ValueError, match="those are the slots the unit writes"):
        ExecUnit("alu", (ADD,), dest_operands=(AOPR_SRC,))


def test_a_unit_may_ask_for_facilities_beyond_its_operands():
    # `needs` is what a stage body wants from the generator's context — a
    # memory port, a redirect, a trap. Requests, not hardware.
    mem = ExecUnit("mem", (LOAD,), src_operands=(AOPR_SRC,),
                   dest_operands=(AOPR_DEST,), needs=("mem",))
    assert mem.needs == ("mem",)
    with pytest.raises(ValueError, match="facility names"):
        ExecUnit("mem", (LOAD,), needs=(3,))


def test_a_unit_without_semantics_is_still_a_description():
    # Only a generator building a real function unit demands them — the same
    # bargain AtomicOperand makes with its name.
    isa = _isa()
    assert len(ALU.stages()) == 1               # one stage by default
    with pytest.raises(NotImplementedError, match="build_exec"):
        ALU.build_exec(None)
    assert isa.unit("alu") is ALU               # and the ISA still builds
