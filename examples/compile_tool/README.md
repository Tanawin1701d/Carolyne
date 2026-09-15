# compile_tool

C sources in, one memory image per memory out. No operating system, no libc,
no syscalls.

```bash
# from the repo root
python -m examples.compile_tool build programs/hello.c
python -m examples.compile_tool build a.c b.c --target rv32im --imem 16K --dmem 8K
python -m examples.compile_tool build programs/hello.c --target mips32
python -m examples.compile_tool layout --target mips32 --imem 16K
python -m examples.compile_tool verify out/hello.elf --target rv32i
```

or from Python:

```python
from examples.compile_tool import build_program

program = build_program(["hello.c"], target="rv32i", imem_bytes=8192, dmem_bytes=4096)
print(program.describe())
program.image.write_files("out/")
```

`examples/` is not installed (pyproject discovers `carolyne*` only), so the
CLI is `python -m ...` from the repo root rather than a console script.

## Targets

| target   | toolchain                | flags                       | verify                                  |
| -------- | ------------------------ | --------------------------- | --------------------------------------- |
| `rv32i`  | `riscv64-unknown-elf-`   | `-march=rv32i  -mabi=ilp32` | against `carolyne.isa.riscv.Rv32i`      |
| `rv32im` | `riscv64-unknown-elf-`   | `-march=rv32im -mabi=ilp32` | against the same description, which carries the M extension since 2026-09-15 |
| `mips32` | `mipsel-linux-gnu-`      | `-march=mips32r2 -mabi=32`  | not verified: no `carolyne/isa/mips` yet |

MIPS32 carries multiply and divide in its base ISA, so there is no `mips32im`
to name. The MIPS build is little-endian (`mipsel`), which is what the ELF
reader, the image writer and the core's load/store unit assume.
`CAROLYNE_RISCV_PREFIX` / `CAROLYNE_MIPS_PREFIX` override the tool prefix.

## What a program gets

`carolyne_io.h` is generated into the build directory beside the images:

```c
#include "carolyne_io.h"

int main(void)
{
    print_str("hello\n");
    print_int(42);
    return 0;                   /* crt0 hands this to the exit door */
}
```

`print_char`, `print_int`, `print_str`, `finish`. Each is a store to a
reserved address in the top 16 bytes of the data region, watched by the
simulation harness. There is no hardware decode, so they cost nothing.

## What it does

1. pick the target (`target.py`) and size a machine (`machine.config_for_sizes`) when it has one
2. derive the memory map from it (`layout.MemoryLayout.from_config`, or `from_sizes` for a target with no machine yet)
3. generate the linker script and the C header from that map
4. compile and link (`toolchain`)
5. decode every instruction against the ISA description (`verify`)
6. flatten the ELF into one image per memory (`image`)

The layout is the reason it stays consistent: it comes from the same
`CPUO3_Config` the hardware is built from, and everything else reads it, so
no address is written down twice.

## Editing the generated files

The linker script and the C header are real files, not strings in Python:

```
template/link.ld.in          -> link.ld
template/carolyne_io.h.in    -> carolyne_io.h
runtime/crt0.S               -> copied unchanged
```

Edit the template, not the copy in the build directory. Markers are `@NAME@`
rather than Python's `{name}`, because both files are written in languages
made of braces and `str.format` would need every one of them doubled;
`render.py` fills them in and refuses a marker nothing fills.

`template/` is for files with markers, `runtime/` for files copied as they
are.

## Things worth knowing

- **`.rodata` goes to the data memory.** The two memories are separate
  hardware and a load reads the data one, so a string literal placed beside
  the code would read back as an instruction word.
- **The code starts at the ISA's `reset_pc`** — `0x00000000` for `Rv32i()`,
  anything else with `Rv32i(reset_pc=...)` — because that is where fetch
  starts after reset. No code base is written in this tool, and the build
  refuses an ELF whose entry is anywhere else.
- **The data region has its own base** (`0x10000000`). The hardware
  part-selects the low address bits, so the base is truncated away before the
  memory sees it; it only makes the ELF and the disassembly readable.
- **`-march=rv32im` is accepted and will fail verification** until the ISA
  description grows multiply µops. That is the point: the build names the
  offending instruction instead of handing the core a word it decodes into
  nothing. With `rv32i`, `*` and `/` work through libgcc's `__mulsi3`.
- **Everything is compiled `-mstrict-align`**, because a misaligned access is
  silently wrong in the load/store unit (`docs/open_items.md`).

## Running the images

The machine that runs them is `examples/o3/core/build.py` (`O3Machine`, any
`CPUO3_Config`); a run harness over Kathryn's `kathryn.sim` is not part of
this tool.
Kathryn's `kathryn.observe` / `kathryn.view` (the recorder and the renderers).
