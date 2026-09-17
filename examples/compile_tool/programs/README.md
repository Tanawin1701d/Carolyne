# Test programs

C programs a generated machine is checked against: each is compiled twice —
by the cross toolchain for the machine, and natively as the ORACLE — and the
run passes only when the machine's console matches the host's, byte for byte
(`python -m examples.sim.rv_sim run <program>.c`).

## From RIDECORE — with our thanks

Eleven of these programs come from the test suite of **RIDECORE** (RIsc-v
Dynamic Execution CORE), the out-of-order RISC-V processor by the Arch Lab,
Tokyo Institute of Technology (<https://github.com/ridecore/ridecore>).
RIDECORE's bare-metal flow — a linker script, memory images, and three
watched I/O words in place of an operating system — is also what this whole
harness is modeled on. Copyright (c) 2016 Arch Lab. Tokyo Institute of
Technology; conditions and disclaimer in [LICENSE.ridecore](LICENSE.ridecore).

| file | upstream | what it exercises |
|--------------|----------------------------|-----------------------------------|
| `acker.c` | `app/acker/main.c` | deep double recursion (Ackermann) |
| `combinat.c` | `app/combinat/main.c` | Pascal's triangle table |
| `cprime.c` | `app/cprime/main.c` | sieve over a 2-D array (needs `--dmem 16384`) |
| `fib.c` | `app/fib/main.c` | naive recursive Fibonacci |
| `hanoi.c` | `app/hanoi/main.c` | recursion with interleaved output |
| `komachi.c` | `app/komachi/main.c` | 3^9 search, long pure compute |
| `riscv_temp.c` | `app/riscv_temp/main.c` | the smallest store sequence |
| `sort_3.c` | `app/sort_3/main.c` | three sort algorithms |
| `stencil.c` | `app/stencil/main.c` | 2-D array reads |
| `stirling.c` | `app/stirling/main.c` | mutual recursion table |
| `tarai.c` | `app/tarai/main.c` | the Takeuchi function |

The port is deliberately MECHANICAL: the algorithms are untouched, and only
RIDECORE's three MMIO doors (`0x0` char, `0x4` int, `0x8` finish) became the
four `carolyne_io.h` calls — which is what keeps a host build of the same
file a valid oracle. Not ported: `charout` (52,000 characters of output) and
`matmul` (multi-file).

## Carolyne's own

`hello.c` (the smallest end-to-end program) and the diagnostics written while
debugging the core, each the smallest reproducer of a bug it caught:
`ldst.c`, `rec.c`, `m4.c`, `fwd.c`, `subword.c` (`docs/open_items.md` has the
stories).
