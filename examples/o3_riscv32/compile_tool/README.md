# compile_tool

C sources in, one memory image per memory out. No operating system, no libc,
no syscalls.

```bash
# from the repo root
python -m examples.o3_riscv32.compile_tool build programs/hello.c
python -m examples.o3_riscv32.compile_tool build a.c b.c --imem 16K --dmem 8K
python -m examples.o3_riscv32.compile_tool layout --imem 16K
python -m examples.o3_riscv32.compile_tool verify out/hello.elf
```

or from Python:

```python
from examples.o3_riscv32.compile_tool import build_program

program = build_program(["hello.c"], imem_bytes=8192, dmem_bytes=4096)
print(program.describe())
program.image.write_files("out/")
```

`examples/` is not installed (pyproject discovers `carolyne*` only), so the
CLI is `python -m ...` from the repo root rather than a console script.

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

1. size a machine (`machine.config_for_sizes`)
2. derive the memory map from it (`layout.MemoryLayout.from_config`)
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

## Not here yet

Running the images. The machine resets its pc to the ISA's `reset_pc` and
fetches from any aligned pc; what is missing is the simulation harness.
