# compile_tool — C sources to two memory images, with no operating system.
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
#
# The tests that run the cross compiler skip when it is absent, so the rest
# still runs on a machine with no RISC-V toolchain.

from __future__ import annotations

import os
import shutil

import pytest

from carolyne.isa.riscv import Rv32i
from carolyne.uarch.o3.config import CPUO3_Config
from examples.o3_riscv32.compile_tool import build_program, config_for_sizes
from examples.o3_riscv32.compile_tool.cheader import render_c_header
from examples.o3_riscv32.compile_tool.image import build_image
from examples.o3_riscv32.compile_tool.layout import (DMEM_BASE, IMEM_BASE,
                                                     MMIO_BYTES, MemoryLayout)
from examples.o3_riscv32.compile_tool.ldscript import render_linker_script
from examples.o3_riscv32.compile_tool.machine import idx_width_for
from examples.o3_riscv32.compile_tool.toolchain import TOOL_PREFIX
from examples.o3_riscv32.compile_tool.verify import decode_hits, verify_program

ISA      = Rv32i()
PROGRAMS = os.path.join(os.path.dirname(__file__), "..", "examples",
                        "o3_riscv32", "compile_tool", "programs")
HELLO    = os.path.abspath(os.path.join(PROGRAMS, "hello.c"))

needs_gcc = pytest.mark.skipif(
    shutil.which(f"{TOOL_PREFIX}gcc") is None,
    reason=f"no {TOOL_PREFIX}gcc on PATH")


def _layout(imem: int = 8192, dmem: int = 4096) -> MemoryLayout:
    return MemoryLayout.from_config(config_for_sizes(imem, dmem))


# --- the whole flow -----------------------------------------------------------
@needs_gcc
def test_a_c_program_becomes_one_image_per_memory(tmp_path):
    """The usage documentation: sources in, two images out."""
    program = build_program([HELLO], imem_bytes=8192, dmem_bytes=4096,
                            name="hello", out_dir=str(tmp_path))

    assert program.report.ok
    assert program.elf.entry == program.layout.reset_pc

    # one bank per front-end lane, and the data memory is always one bank
    assert len(program.image.instr_banks) == program.config.fe_lanes
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
    program = build_program([HELLO], name="hello", out_dir=str(tmp_path))
    where   = {p.section: p.region for p in program.image.placements}

    assert where[".text"]   == "imem"
    assert where[".rodata"] == "dmem"


# --- the layout ---------------------------------------------------------------
def test_the_layout_takes_its_sizes_from_the_config_the_hardware_is_built_from():
    config = config_for_sizes(8192, 4096)
    layout = MemoryLayout.from_config(config)

    assert layout.imem_bytes == config.instr_mem_spec().size_bytes
    assert layout.dmem_bytes == config.data_mem_spec().size_bytes
    assert layout.imem_banks == config.fe_lanes


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
        MemoryLayout(imem_base=IMEM_BASE, imem_bytes=imem, imem_banks=2,
                     imem_idx_width=10, dmem_base=DMEM_BASE, dmem_bytes=dmem,
                     dmem_idx_width=10, word_bytes=4)


def test_a_region_base_that_the_hardware_would_not_truncate_away_is_refused():
    with pytest.raises(ValueError, match="not a multiple"):
        MemoryLayout(imem_base=IMEM_BASE, imem_bytes=8192, imem_banks=2,
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
    from examples.o3_riscv32.compile_tool.elf32 import Elf32, Section

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
    script = render_linker_script(layout)
    header = render_c_header(layout)

    for name, addr in layout.mmio_addrs.items():
        assert f"__mmio_{name}" in script
        assert f"0x{addr:08x}" in script
        assert f"0x{addr:08x}" in header

    assert f"0x{layout.stack_top:08x}" in script
    assert f"ORIGIN = 0x{layout.imem_base:08x}" in script
    assert f"LENGTH = {layout.data_bytes}" in script


def test_the_linker_script_keeps_read_only_data_out_of_the_instruction_memory():
    script = render_linker_script(_layout())
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


def test_a_multiply_matches_no_uop_because_the_isa_has_no_m_extension():
    """This is what makes -march=rv32im safe to offer: the build refuses
    rather than handing the core a word it decodes into nothing."""
    mul = 0x02E787B3        # mul a5, a5, a4

    assert decode_hits(mul, _levels()) == ()


@needs_gcc
def test_building_for_rv32im_fails_and_names_the_instruction(tmp_path):
    source = tmp_path / "mul.c"
    source.write_text("volatile int a = 7, b = 6;\n"
                      "int main(void) { return a * b; }\n")

    with pytest.raises(ValueError, match="cannot be decoded"):
        build_program([str(source)], name="mul", march="rv32im",
                      out_dir=str(tmp_path / "out"))


@needs_gcc
def test_the_same_multiply_builds_for_rv32i_through_a_libgcc_call(tmp_path):
    """With no M extension GCC turns `*` into a call to __mulsi3, which is
    why the link line states -lgcc."""
    source = tmp_path / "mul.c"
    source.write_text("volatile int a = 7, b = 6;\n"
                      "int main(void) { return a * b; }\n")

    program = build_program([str(source)], name="mul", march="rv32i",
                            out_dir=str(tmp_path / "out"))
    assert program.report.ok


def _levels():
    from carolyne.uarch.o3.decode import group_uops_by_level
    return group_uops_by_level(ISA)
