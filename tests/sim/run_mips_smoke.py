# A hand-assembled MIPS32 program through the real simulator — no compiler.
#
# Run as its own PROCESS (tests/test_by_ai/test_mips32_smoke.py does):
# Kathryn's emitted names come from a process-global counter, so a compiled
# simulator only serves an emit made in the same build order.
#
# The program exercises the paths a compiled program would first hit: fetch
# from the architectural reset vector, lui/ori/addiu, stores to the console
# doors, mult/mflo through HI and LO, a data-memory round trip, one taken and
# one not-taken branch (each with a nop in its delay slot), and the exit door.

from __future__ import annotations

import json
import os
import pathlib
import sys
import types

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.chdir(REPO)

from examples.compile_tool.elf32 import Elf32, Section                        # noqa: E402
from examples.compile_tool.image import build_image                           # noqa: E402
from examples.compile_tool.layout import MemoryLayout                         # noqa: E402
from examples.o3.core.mem_size import machine_mem_of                          # noqa: E402
from examples.o3.sim.run_spec import SPEC_ENV, SPEC_FILE, build_run_spec, write_run_spec  # noqa: E402
from examples.o3.sim.system import emit_machine                              # noqa: E402
from examples.o3.mips32.config import TARGET, gen_o3_mips32_config_for_sizes  # noqa: E402
from examples.o3.mips32.sim import TEST_CASE, TEST_MODULE                    # noqa: E402
from examples.sim.options import SimOptions                                   # noqa: E402
from examples.sim.runner import SIM_ROOT, run_system                          # noqa: E402
from examples.sim.system import SimSystem                                     # noqa: E402

NAME    = "mips_smoke"
EXPECT  = "Hi\n4242*"

WORDS = (
    0x3C081000,   # lui   $8, 0x1000
    0x35080FF0,   # ori   $8, $8, 0x0ff0        $8 = putchar door (putint +4, exit +8)
    0x24090048,   # addiu $9, $0, 'H'
    0xAD090000,   # sw    $9, 0($8)             putchar H
    0x24090069,   # addiu $9, $0, 'i'
    0xAD090000,   # sw    $9, 0($8)             putchar i
    0x2409000A,   # addiu $9, $0, '\n'
    0xAD090000,   # sw    $9, 0($8)
    0x240A0006,   # addiu $10, $0, 6
    0x240B0007,   # addiu $11, $0, 7
    0x014B0018,   # mult  $10, $11
    0x00006012,   # mflo  $12                   42
    0xAD0C0004,   # sw    $12, 4($8)            putint 42
    0xAD0CFFF0,   # sw    $12, -16($8)          data memory round trip
    0x8D0EFFF0,   # lw    $14, -16($8)
    0xAD0E0004,   # sw    $14, 4($8)            putint 42 again
    0x10000002,   # beq   $0, $0, +2            taken: skip the nop and the bad store
    0x00000000,   # nop                         (delay slot)
    0xAD090004,   # sw    $9, 4($8)             NOT executed
    0x114B0002,   # beq   $10, $11, +2          not taken (6 != 7)
    0x00000000,   # nop
    0xAD0C0000,   # sw    $12, 0($8)            putchar '*'
    0x240D0000,   # addiu $13, $0, 0
    0xAD0D0008,   # sw    $13, 8($8)            exit(0)
    0x1000FFFF,   # loop: beq $0, $0, -1
    0x00000000,   # nop
)


def main() -> int:
    config, knobs = gen_o3_mips32_config_for_sizes(8192, 4096, fe_lanes=2)
    layout  = MemoryLayout.from_spec(machine_mem_of(config))
    blob    = b"".join(w.to_bytes(4, "little") for w in WORDS)
    text    = Section(name=".text", type=1, flags=0x6, addr_target_mem=layout.imem_base,
                      offset_in_elf=0, size_bytes=len(blob))
    elf     = Elf32(path="<smoke>", entry=layout.imem_base, machine=8, sections=(text,), _raw=blob)
    image   = build_image(elf, layout)

    run_dir = str(SIM_ROOT / "run" / NAME)
    rtl_dir = os.path.join(run_dir, "rtl")
    image.write_files(os.path.join(run_dir, "program"))
    emit_machine(config, rtl_dir)

    program   = types.SimpleNamespace(layout=layout, image=image)
    spec_path = os.path.join(rtl_dir, SPEC_FILE)
    write_run_spec(spec_path, build_run_spec(config, program, run_dir, name=NAME, target=TARGET,
                                             log_enabled=False, log_window=0, log_chunk=0,
                                             log_rob_rows=0, max_cycles=2_000, idle_limit=500,
                                             knobs=knobs))
    system = SimSystem(name=NAME, run_dir=run_dir, rtl_dir=rtl_dir, test_module=TEST_MODULE,
                       test_case=TEST_CASE, env={SPEC_ENV: spec_path}, c_sources=())
    result = run_system(system, SimOptions(sim="verilator", waves=False, expect="none"))
    print("RESULT " + json.dumps({"stop_reason": result.stop_reason, "cycles": result.cycles,
                                  "exit_code": result.exit_code, "console": result.console}))
    return 0 if (result.stop_reason == "exit" and result.console == EXPECT) else 1


if __name__ == "__main__":
    sys.exit(main())
