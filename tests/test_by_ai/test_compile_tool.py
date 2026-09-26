# compile_tool — C sources to two memory images, with no operating system,
# for any target the tool describes (rv32im, mips32).
#
# The first test is the usage documentation: size a machine, derive the
# layout, build, and read the images back.
#
# What these pin, in order of how badly a break would hurt:
#   * the layout is DERIVED from the config, so the images and the hardware
#     cannot disagree about a size or a bank count
#   * the bank interleave matches uarch/o3/fetch.py's rule, checked by
#     round-tripping words through the image and back
#   * every instruction is held to the ISA's own encoding table, so a
#     program the machine could not decode fails the BUILD
#   * the code starts at the ISA's reset_pc, the address fetch starts from
#   * mips32 is verified against its own description, and its branch delay
#     slots must hold the nop the engine squashes
#
# The tests that run the cross compiler skip when it is absent, so the rest
# still runs on a machine with no RISC-V toolchain.

from __future__ import annotations

import dataclasses
import os
import shutil

import pytest

from carolyne.isa.mips import Mips32
from carolyne.isa.riscv import Rv32im
from carolyne.uarch.o3.config import CPUO3_Config
from examples.compile_tool import (MIPS32, RV32IM, TARGETS, _reject_wrong_entry,
                                   build_program, target_named)
from examples.o3.rv32im.config import gen_o3_rv32im_config_for_sizes
from examples.compile_tool.cheader import render_c_header
from examples.compile_tool.image import build_image
from examples.compile_tool.layout import DMEM_BASE, MMIO_BYTES, MemoryLayout, MachineMem
from examples.compile_tool.ldscript import render_linker_script
from examples.o3.core.mem_size import idx_width_for, machine_mem_of
from examples.compile_tool.verify import decode_hits, verify_program

ISA      = Rv32im()
PROGRAMS = os.path.join(os.path.dirname(__file__), "..", "..", "examples", "compile_tool", "programs")
HELLO    = os.path.abspath(os.path.join(PROGRAMS, "hello.c"))

needs_gcc  = pytest.mark.skipif(shutil.which(RV32IM.tool("gcc")) is None,
                                reason=f"no {RV32IM.tool('gcc')} on PATH")
needs_mips = pytest.mark.skipif(shutil.which(MIPS32.tool("gcc")) is None,
                                reason=f"no {MIPS32.tool('gcc')} on PATH")


def a_config(imem: int = 8192, dmem: int = 4096, **knobs) -> CPUO3_Config:
    """The machine these tests lay out for — the caller's choice, as the sim makes it."""
    config, _knobs = gen_o3_rv32im_config_for_sizes(imem, dmem, **knobs)
    return config


def a_machine_mem(imem: int = 8192, dmem: int = 4096, **knobs) -> MachineMem:
    """That machine's memories, as build_program takes them."""
    return machine_mem_of(a_config(imem, dmem, **knobs))


def _layout(imem: int = 8192, dmem: int = 4096) -> MemoryLayout:
    return MemoryLayout.from_spec(a_machine_mem(imem, dmem))


def _config_at(reset_pc: int) -> CPUO3_Config:
    """The default machine on an RV32I whose fetch starts at `reset_pc`."""
    return dataclasses.replace(a_config(), isa=Rv32im(reset_pc=reset_pc))


# --- the whole flow -----------------------------------------------------------
@needs_gcc
def test_a_c_program_becomes_one_image_per_memory(tmp_path):
    """The usage documentation: a machine and sources in, two images out."""
    config      = a_config(8192, 4096)
    machine_mem = machine_mem_of(config)
    program     = build_program([HELLO], machine_mem,
                            name="hello", out_dir=str(tmp_path))

    assert program.report.ok and program.target is RV32IM
    assert program.elf.entry == program.layout.reset_pc

    # one bank per front-end lane, and the data memory is always one bank
    assert len(program.image.instr_banks) == machine_mem.imem_banks == config.fe_lanes
    assert len(program.image.data_bank.words) == program.layout.dmem_words

    # the program really is in there: something was written to both memories
    assert program.image.instr_banks[0].used_words > 0
    assert program.image.data_bank.used_words > 0


@needs_gcc
def test_code_goes_to_the_instruction_memory_and_read_only_data_to_the_data_one(tmp_path):
    """.rodata must land in DMEM: a load reads the DATA memory.

    A single-memory linker script would put string literals beside the code,
    and every read of one would return an instruction word instead.
    """
    program = build_program([HELLO], a_machine_mem(), name="hello", out_dir=str(tmp_path))
    where   = {p.section: p.region for p in program.image.placements}

    assert where[".text"]   == "imem"
    assert where[".rodata"] == "dmem"


@needs_gcc
def test_moving_the_reset_vector_moves_the_program_with_it(tmp_path):
    """_start, the ELF entry and the first code word all follow reset_pc."""
    program = build_program([HELLO], machine_mem_of(_config_at(0x80000000)),
                            name="hello", out_dir=str(tmp_path))
    text    = next(s for s in program.elf.sections if s.name == ".text")
    first   = int.from_bytes(program.elf.bytes_of(text)[:4], "little")

    assert program.report.ok
    assert program.elf.entry        == 0x80000000
    assert text.addr_target_mem     == 0x80000000
    assert program.layout.instr_slot(0x80000000) == (0, 0)
    assert program.image.instr_banks[0].words[0] == first


@needs_gcc
def test_a_program_linked_for_another_reset_vector_is_refused(tmp_path):
    """The linker script always agrees today, so the guard is called directly:
    an ELF built for reset 0 must not load into a core that starts elsewhere."""
    program = build_program([HELLO], a_machine_mem(), name="hello", out_dir=str(tmp_path))

    with pytest.raises(ValueError, match="reset_pc is 0x80000000"):
        _reject_wrong_entry(program.elf,
                            MemoryLayout.from_spec(machine_mem_of(_config_at(0x80000000))))


# --- the layout ---------------------------------------------------------------
def test_the_layout_takes_its_sizes_from_the_config_the_hardware_is_built_from():
    config = a_config(8192, 4096)
    layout = MemoryLayout.from_spec(machine_mem_of(config))

    assert layout.imem_bytes == config.instr_mem_spec().size_bytes
    assert layout.dmem_bytes == config.data_mem_spec().size_bytes
    assert layout.imem_banks == config.fe_lanes


def test_the_code_region_starts_where_the_isa_says_fetch_starts():
    """No code base is stated anywhere: it is the ISA's reset_pc."""
    assert _layout().imem_base == ISA.reset_pc
    assert MemoryLayout.from_spec(machine_mem_of(_config_at(0x80000000))).imem_base == 0x80000000


def test_a_reset_vector_inside_the_data_region_is_refused():
    """The code region moves with reset_pc, so it can land on the data."""
    with pytest.raises(ValueError, match="overlaps the data region"):
        MemoryLayout.from_spec(machine_mem_of(_config_at(DMEM_BASE)))


def test_the_io_words_sit_above_the_allocatable_end_of_the_data_region():
    layout = _layout()

    assert layout.data_limit == layout.dmem_limit - MMIO_BYTES
    assert layout.stack_top  == layout.data_limit
    for addr in layout.mmio_addrs.values():
        assert layout.data_limit <= addr < layout.dmem_limit


def test_a_store_address_is_named_only_when_it_is_an_io_word():
    layout = _layout()

    assert layout.mmio_name_at(layout.mmio_addrs["exit"]) == "exit"
    assert layout.mmio_name_at(layout.dmem_base) == ""


@pytest.mark.parametrize("imem,dmem,why", [
    (8192 + 4, 4096, "power of two"),
    (8192, 4096 + 4, "power of two"),
    (8192, 16,       "leaves nothing under"),
])
def test_a_layout_the_hardware_could_not_address_is_refused(imem, dmem, why):
    """The address is a part-select, so a size that is not a power of two
    would not be masked and every access would land somewhere else."""
    with pytest.raises(ValueError, match=why):
        MemoryLayout(imem_base=0, imem_bytes=imem, imem_banks=2,
                     imem_idx_width=10, dmem_base=DMEM_BASE, dmem_bytes=dmem,
                     dmem_idx_width=10, word_bytes=4)


def test_a_region_base_that_the_hardware_would_not_truncate_away_is_refused():
    with pytest.raises(ValueError, match="not a multiple"):
        MemoryLayout(imem_base=0, imem_bytes=8192, imem_banks=2,
                     imem_idx_width=10, dmem_base=DMEM_BASE + 4,
                     dmem_bytes=4096, dmem_idx_width=10, word_bytes=4)


# --- sizes --------------------------------------------------------------------
@pytest.mark.parametrize("total,banks,word,want", [
    (8192, 2, 4, 10),      # the default machine: 2 banks of 1024 words
    (8192, 1, 4, 11),      # one lane: the same bytes need one more index bit
    (4096, 1, 4, 10),
])
def test_a_byte_size_becomes_the_index_width_one_bank_needs(total, banks, word, want):
    assert idx_width_for(total, banks, word) == want


def test_a_size_that_does_not_divide_into_the_banks_is_refused():
    with pytest.raises(ValueError, match="power of two"):
        idx_width_for(8192 + 4, 2, 4)


def test_the_layout_derives_the_same_widths_as_the_machine_side():
    """from_spec's private twin and examples/o3's idx_width_for may not drift."""
    layout = _layout(8192, 4096)
    assert layout.imem_idx_width == idx_width_for(8192, layout.imem_banks, 4)
    assert layout.dmem_idx_width == idx_width_for(4096, 1, 4)


# --- the bank interleave ------------------------------------------------------
def test_the_bank_interleave_matches_the_rule_fetch_reads():
    """Word w is in bank w % banks at index w // banks (uarch/o3/fetch.py)."""
    layout = _layout()

    for word in range(8):
        addr = layout.imem_base + word * layout.word_bytes
        assert layout.instr_slot(addr) == (word % layout.imem_banks,
                                           word // layout.imem_banks)


def test_words_written_into_the_code_image_come_back_out_in_address_order():
    """The round trip is the real check: de-interleaving is easy to get
    backwards, and a swapped bank runs the program in the wrong order."""
    layout = _layout()
    words  = [0x1000_0000 + i for i in range(16)]

    image = _image_of_code(layout, words)
    back  = []
    for i in range(len(words)):
        bank, index = layout.instr_slot(layout.imem_base + i * 4)
        back.append(image.instr_banks[bank].words[index])

    assert back == words


def _image_of_code(layout: MemoryLayout, words) -> "object":
    """An image holding these words at the start of the code region."""
    from examples.compile_tool.elf32 import Elf32, Section

    blob = b"".join(w.to_bytes(4, "little") for w in words)
    text = Section(name=".text", type=1, flags=0x2 | 0x4,
                   addr_target_mem=layout.imem_base, offset_in_elf=0,
                   size_bytes=len(blob))
    elf  = Elf32(path="<test>", entry=layout.imem_base, machine=243,
                 sections=(text,), _raw=blob)
    return build_image(elf, layout)


# --- the generated files ------------------------------------------------------
def test_the_linker_script_and_the_c_header_state_the_layouts_own_addresses():
    """Both are generated from one object, which is what keeps a program and
    the thing watching the store port agreeing about where a character goes."""
    layout = _layout()
    script = render_linker_script(layout, RV32IM)
    header = render_c_header(layout)

    for name, addr in layout.mmio_addrs.items():
        assert f"__mmio_{name}" in script
        assert f"0x{addr:08x}" in script
        assert f"0x{addr:08x}" in header

    assert f"0x{layout.stack_top:08x}" in script
    assert f"ORIGIN = 0x{layout.imem_base:08x}" in script
    assert f"LENGTH = {layout.data_bytes}" in script


def test_the_linker_script_keeps_read_only_data_out_of_the_instruction_memory():
    script = render_linker_script(_layout(), RV32IM)
    text   = script.index(".text")
    rodata = script.index(".rodata")

    assert "> IMEM" in script[text:rodata]
    assert "> DMEM" in script[rodata:]


# --- the ISA check ------------------------------------------------------------
def test_every_rv32i_encoding_the_compiler_emits_picks_exactly_one_uop():
    """add x1,x2,x3 and addi x1,x2,4 are the two shapes everything else
    follows; a word matching zero µops would decode into an empty lane."""
    add  = 0x003100B3
    addi = 0x00410093

    assert [u.name for u in decode_hits(add,  _levels())] == ["ADD"]
    assert [u.name for u in decode_hits(addi, _levels())] == ["ADDI"]


def test_a_multiply_picks_exactly_the_m_uop():
    """The M rows share every funct3 with the base OP rows and differ in
    funct7, so a base row that stated funct3 alone would claim it too."""
    mul  = 0x02E787B3        # mul  a5, a5, a4
    divu = 0x02F757B3        # divu a5, a4, a5
    sll  = 0x00F717B3        # sll  a5, a4, a5: funct7 0000000

    assert [u.name for u in decode_hits(mul,  _levels())] == ["MUL"]
    assert [u.name for u in decode_hits(divu, _levels())] == ["DIVU"]
    assert [u.name for u in decode_hits(sll,  _levels())] == ["SLL"]


@needs_gcc
def test_building_for_rv32im_verifies_the_multiply(tmp_path):
    """The multiply compiles to MUL, and the description now decodes it."""
    source = tmp_path / "mul.c"
    source.write_text("volatile int a = 7, b = 6;\n"
                      "int main(void) { return a * b; }\n")

    program = build_program([str(source)], a_machine_mem(), name="mul", target="rv32im",
                            out_dir=str(tmp_path / "out"))
    assert program.report.ok and program.build.target == "rv32im"
    assert any(u.name == "MUL" for word in _text_words(program)
               for u in decode_hits(word, _levels()))


def _text_words(program):
    text = next(s for s in program.elf.sections if s.name == ".text")
    blob = program.elf.bytes_of(text)
    return [int.from_bytes(blob[i:i + 4], "little") for i in range(0, len(blob), 4)]


@needs_gcc
def _levels():
    from carolyne.uarch.o3.decode import group_uops_by_level
    return group_uops_by_level(ISA)


# --- targets ------------------------------------------------------------------
def test_a_target_is_named_and_an_unknown_one_lists_the_choices():
    assert target_named("rv32im") is RV32IM and target_named("mips32") is MIPS32
    with pytest.raises(ValueError, match="rv32im, mips32"):
        target_named("arm")


def test_rv32im_is_the_one_riscv_target():
    assert RV32IM.arch_flags == ("-march=rv32im", "-mabi=ilp32")
    assert RV32IM.isa is Rv32im and RV32IM.can_verify
    assert RV32IM.crt0 == "crt0_riscv.S"
    assert "rv32i" not in TARGETS          # the no-M variant bought nothing


def test_mips32_verifies_against_its_description_and_holds_its_slots_to_a_nop():
    """MIPS32 carries multiply/divide in its base ISA: there is no 'im' to name."""
    assert MIPS32.isa is Mips32 and MIPS32.can_verify
    assert MIPS32.reset_pc == Mips32().reset_pc == 0xBFC00000
    assert MIPS32.arch_flags == ("-march=mips32r2", "-mabi=32", "-msoft-float", "-mno-abicalls")
    assert "-fno-delayed-branch" in MIPS32.cflags and "-mno-imadd" in MIPS32.cflags
    assert MIPS32.delay_slot_nop == 0 and RV32IM.delay_slot_nop is None


def test_the_linker_script_is_the_targets():
    layout = MemoryLayout.from_spec(MIPS32.machine_mem(8192, 4096, banks=2))
    mips   = render_linker_script(layout, MIPS32)
    riscv  = render_linker_script(_layout(), RV32IM)

    assert "OUTPUT_ARCH(mips)" in mips and "_gp = . + 0x7ff0;" in mips
    assert "*(.MIPS.abiflags)" in mips and ".riscv.attributes" not in mips
    assert "OUTPUT_ARCH(riscv)" in riscv and "__global_pointer$" in riscv
    assert "*(.riscv.attributes)" in riscv and ".MIPS.abiflags" not in riscv


def test_a_target_with_no_machine_states_its_own_machine_mem():
    """The same shape a config derives, so the images fit the machine to come."""
    layout  = MemoryLayout.from_spec(MIPS32.machine_mem(8192, 4096, banks=2))
    from_rv = MemoryLayout.from_spec(a_machine_mem(8192, 4096, fe_lanes=2))

    assert layout.imem_base == MIPS32.reset_pc == 0xBFC00000
    assert (layout.imem_bytes, layout.imem_banks, layout.imem_idx_width) == \
           (from_rv.imem_bytes, from_rv.imem_banks, from_rv.imem_idx_width)
    assert (layout.dmem_bytes, layout.dmem_idx_width, layout.word_bytes) == \
           (from_rv.dmem_bytes, from_rv.dmem_idx_width, from_rv.word_bytes)


def test_the_build_takes_the_memories_it_lays_out_for():
    """`mem` is REQUIRED, and a target carries no machine: the memories a
    build lays out for arrive as build_program's own argument."""
    with pytest.raises(TypeError):
        build_program([HELLO])                   # no mem: refused before any tool runs
    assert target_named("rv32im") is RV32IM      # one arg, the shared constant


def test_a_machine_config_and_its_machine_mem_cannot_disagree():
    """machine_mem_of DERIVES, so the layout ends up with the hardware's own widths."""
    config      = a_config(8192, 4096, fe_lanes=2)
    machine_mem = machine_mem_of(config)
    assert (machine_mem.imem_bytes, machine_mem.dmem_bytes, machine_mem.imem_banks) == (8192, 4096, 2)
    assert machine_mem.imem_base == config.reset_pc

    layout = MemoryLayout.from_spec(machine_mem)
    assert layout.imem_idx_width == config.instr_mem_spec().index_width
    assert layout.dmem_idx_width == config.data_mem_spec().index_width


@needs_mips
def test_a_mips_program_builds_and_is_verified(tmp_path):
    program = build_program([HELLO], MIPS32.machine_mem(banks=2), target="mips32",
                            name="hello", out_dir=str(tmp_path))

    assert program.report.ok and not program.report.skipped
    assert program.report.checked > 0 and program.report.isa_name == "mips32"
    assert program.elf.entry == MIPS32.reset_pc
    assert program.image.instr_banks[0].used_words > 0


def _mips_text(words, base=0xBFC00000):
    """An ELF holding these words as its whole text, for verify alone."""
    from examples.compile_tool.elf32 import Elf32, Section
    blob = b"".join(w.to_bytes(4, "little") for w in words)
    text = Section(name=".text", type=1, flags=0x2 | 0x4, addr_target_mem=base,
                   offset_in_elf=0, size_bytes=len(blob))
    return Elf32(path="<test>", entry=base, machine=8, sections=(text,), _raw=blob)


def test_a_branch_whose_delay_slot_is_not_the_nop_is_refused():
    """The engine squashes the word after a taken branch, so only a nop may stand there."""
    beq   = 4 << 26 | 1 << 21 | 2 << 16 | 3          # beq $1,$2,+12
    addiu = 9 << 26 | 1 << 21 | 1 << 16 | 4          # addiu $1,$1,4
    nop   = 0
    isa   = Mips32()

    good = verify_program(_mips_text([beq, nop, addiu]), isa, delay_slot_nop=0)
    assert good.ok and good.checked == 3

    bad = verify_program(_mips_text([beq, addiu, nop]), isa, delay_slot_nop=0)
    assert [p.kind for p in bad.problems] == ["delay slot"]
    assert bad.problems[0].hits == ("BEQ",) and bad.problems[0].slot == addiu
    assert "not the nop" in str(bad.problems[0])
    with pytest.raises(ValueError, match="delay slot"):
        bad.raise_if_bad()

    last = verify_program(_mips_text([addiu, beq]), isa, delay_slot_nop=0)
    assert [p.kind for p in last.problems] == ["delay slot"] and last.problems[0].slot is None
    assert "missing" in str(last.problems[0])

    # no rule: the machine executes the slot, so anything may stand there
    assert verify_program(_mips_text([beq, addiu, nop]), isa).ok
