# Carolyne

An **ISA-agnostic out-of-order CPU generator**, written in Python on top of the
[Kathryn](https://github.com/Tanawin1701d/Kathryn) hardware-construction library.

The out-of-order engine (fetch, rename, issue, execute, commit) is written
once, against a fixed *µop contract*. An ISA is a small Python description
package: register classes, encodings and execution semantics. At elaboration
time the engine builds its rename tables, decoder, physical register files and
commit logic from that description.

This repository demonstrates **one engine with two ISAs, RV32IM and MIPS32**.
Both run the same 17 C programs in simulation and on an AMD KV260 board at
50 MHz. On the board, every program's cycle count equals the simulator's.

- [Reproduce the results](#reproduce-the-results): one command, simulator and board
- [Results](#results): what the command printed on our KV260
- [Layout](#layout) and [Development](#development): for working on the code

---

## Reproduce the results

`examples/run_experiment.py` runs every program on both ISAs, first in the
simulator, then on the board, and compares each run three ways:

| check | passes when |
|---|---|
| host vs simulator | the simulator stops on the program's exit and prints what a host build of the same C prints |
| host vs board | the same, for the board run |
| simulator vs board | stop reason, exit code, console text and the **exact cycle count** are equal |

### 1. What you need

| | version we used | needed for |
|---|---|---|
| Linux PC | Ubuntu 22.04, 15 GB RAM | everything |
| Python | 3.13 (3.9+ works) | everything |
| Rust toolchain (`cargo`) | stable | building Kathryn |
| `riscv64-unknown-elf-gcc` | Ubuntu package `gcc-riscv64-unknown-elf` | compiling the RV32IM programs |
| `mipsel-linux-gnu-gcc` | Ubuntu package `gcc-mipsel-linux-gnu` (10.3) | compiling the MIPS32 programs |
| `gcc` | any | the host build every run is checked against |
| AMD Vivado | 2023.2 | building the bitstreams |
| `ssh`, `scp`, `sshpass` | any | reaching the board |
| AMD KV260 | PYNQ 3.0.1 image | the board runs |

A different cross-compiler prefix is set with `CAROLYNE_RISCV_PREFIX` or
`CAROLYNE_MIPS_PREFIX`. Vivado installed elsewhere than
`/tools/Xilinx/Vivado/2023.2/bin/vivado` is set with `VIVADO`.

### 2. Install

Carolyne and Kathryn are two repositories, cloned side by side:

```bash
git clone https://github.com/Tanawin1701d/Kathryn.git   Kathryn2
git clone --recurse-submodules https://github.com/Tanawin1701d/Carolyne.git
cd Carolyne

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,sim]"      # Carolyne, pytest, cocotb and Verilator
pip install -e ../Kathryn2       # Kathryn (not on PyPI); pip builds its Rust core

pytest tests -q -m "not slow"    # a quick check that the install works
```

`--recurse-submodules` fetches `examples/compile_tool`, the C-to-memory-image
tool. If you cloned without it, run `git submodule update --init`.

### 3. Prepare the board

1. Flash the KV260's SD card with the **PYNQ 3.0.1** image, boot it, and connect
   it to the same network as the PC. Check that `ssh root@<board-ip>` works.
2. Describe the board in a login file. Copy the example and fill it in:

   ```bash
   cp examples/fpga/board/board.example.json examples/fpga/board/board.local.json
   ```

   ```json
   {
     "host"          : "192.168.1.149",
     "port"          : 22,
     "user"          : "root",
     "password"      : "<the board's root password, or null to use an ssh key>",
     "key_path"      : null,
     "remote_dir"    : "/root/jupyter_notebooks/calolyne_test",
     "python"        : "python3",
     "shell_prelude" : "source /etc/profile.d/pynq_venv.sh"
   }
   ```

   | field | meaning |
   |---|---|
   | `host`, `port`, `user` | how ssh reaches the board |
   | `password` | passed to `sshpass` through the environment, never on a command line; `null` uses an ssh key |
   | `key_path` | an ssh key file, when it is not the default one in `~/.ssh` |
   | `remote_dir` | where bitstreams and programs are uploaded; under `jupyter_notebooks` the runs are visible in Jupyter |
   | `shell_prelude` | runs before the board script, so it uses PYNQ's Python |

   `board.local.json` is gitignored. To keep the file somewhere else, pass
   `--board-link <file>` or set `CAROLYNE_BOARD=<file>`.

   The board login is read only when the board half of the first ISA starts,
   after its simulator half. Check this file before a long run.

### 4. Run

```bash
python -m examples.run_experiment
```

| option | default | meaning |
|---|---|---|
| `--targets rv32im mips32` | both | which ISAs to run |
| `--programs hello.c fib.c` | all 17 | file names under `examples/compile_tool/programs/` |
| `--clock-mhz` | `50` | the bitstream's clock |
| `--jobs` | `4` | Vivado jobs; 4 keeps the MIPS32 build under 15 GB of RAM |
| `--board-link` | `board.local.json` | the board login file |

Start with one program to check the whole chain before the full run:

```bash
python -m examples.run_experiment --targets rv32im --programs hello.c
```

The command exits with status 0 only when every row passes.

**How long it takes.** Bitstreams and compiled simulators are cached by the
content of the generated Verilog, so only the first run builds them:

| step | first run | later runs |
|---|---|---|
| Verilator build, per ISA | ~4 min | cached |
| Vivado bitstream, RV32IM | ~19 min | cached |
| Vivado bitstream, MIPS32 | ~25 min | cached |
| 17 programs in the simulator, per ISA | ~7 min | ~7 min |
| 17 programs on the board, per ISA | ~2 min | ~2 min |

With both bitstreams cached, the full run took 878 s on our machine.

### 5. Output

Everything goes under `generated/experiment/`:

| path | contents |
|---|---|
| `results.txt` | the table printed at the end |
| `results.json` | every run and every verdict |
| `<isa>/sim/<program>/` | the simulator run: images, `result.json`, `console.txt` |
| `<isa>/fpga/<program>/` | the board run, and `compare.json` (simulator vs board) |

The bitstreams are in `generated/fpga/vivado/<key>/export/`, with Vivado's
timing and utilization reports beside them.

### Troubleshooting

| message | cause |
|---|---|
| `no board link file at ...` | step 3.2 was skipped, or `--board-link` names a missing file |
| `riscv64-unknown-elf-gcc not found` | install the cross-compiler, or set `CAROLYNE_RISCV_PREFIX` |
| Vivado not found | set `VIVADO` to the `vivado` binary |
| `REG_MAGIC reads ...` | the board is not running a Carolyne bitstream, or the link is broken |
| `REG_GEOMETRY reads ...` | the bitstream was built for other memory sizes; delete its cache folder and rerun |
| a program `TRUNC` or `CONSOLE_OVERFLOW` | the program printed more than the 8192-entry console buffer holds |

---

## Results

`python -m examples.run_experiment` on our KV260, 50 MHz, `-O2`, 2 fetch lanes,
8 KB instruction memory, 16 KB data memory. **34 of 34 passed**: every console
matches the host build, and every board cycle count equals the simulator's.

| program | RV32IM cycles | MIPS32 cycles |
|---|---:|---:|
| riscv_temp | 34 | 34 |
| m4 | 44 | 44 |
| rec | 45 | 45 |
| fwd | 49 | 50 |
| ldst | 51 | 50 |
| subword | 61 | 58 |
| hello | 244 | 264 |
| fib | 3,151 | 3,391 |
| stencil | 4,896 | 4,565 |
| sort_3 | 6,215 | 6,112 |
| hanoi | 11,052 | 9,854 |
| acker | 20,414 | 24,950 |
| stirling | 32,134 | 33,844 |
| combinat | 53,806 | 52,098 |
| cprime | 170,743 | 167,850 |
| tarai | 222,545 | 247,744 |
| komachi | 1,744,749 | 1,709,329 |

Implementation on the KV260 (Vivado 2023.2, after routing):

| ISA | clock | WNS | LUTs | FFs | DSPs | BRAM |
|---|---|---:|---:|---:|---:|---:|
| RV32IM | 50 MHz | +0.307 ns | 66,066 | 19,921 | 21 | 0 |
| MIPS32 | 50 MHz | +0.135 ns | 77,427 | 24,128 | 17 | 0 |

The memories are inside the generated design, with the same timing as in the
simulator. That is why the board's cycle counts can be compared exactly.

---

## Layout

| path | contents |
|---|---|
| `docs/design/uop_contract.md` | the normative spec of the ISA ↔ µarch boundary |
| `carolyne/isa/` | description types, the ISA-facing apis, and the ISA packages `riscv/` and `mips/` |
| `carolyne/uarch/` | the generic out-of-order engine, built from Kathryn primitives |
| `examples/o3/` | the machine (`core/`), its simulator side (`sim/`), its FPGA side (`fpga/`), and one folder per ISA family |
| `examples/sim/` | runs a built machine's programs in Verilator through cocotb |
| `examples/fpga/` | a built machine to a bitstream (`backend/`), to the board (`board/`), compared with the simulator (`compare.py`) |
| `examples/fpga/bridge/` | the HostBridge: how the board's processor loads, starts and reads back the core |
| `examples/compile_tool/` | submodule: C sources to memory images for RV32IM and MIPS32 |
| `examples/run_experiment.py` | the experiment above |
| `generated/` | emitted Verilog, simulators, bitstreams, runs (gitignored) |
| `tests/` | the pytest suite |

Dependency rules: `isa` never imports `uarch`, and its description types
never import `kathryn` (an ISA's execution semantics may). `uarch` may import
the description types but never names a specific ISA.

---

## Development

Run the tests with `pytest tests -q -m "not slow"`. The `slow` marker covers
every test that builds a simulator.

The other entry points, each with `--help`:

```bash
python -m examples.sim run hello.c              # one program in the simulator
python -m examples.sim.sweep --target mips32    # every program in the simulator
python -m examples.fpga build --clock-mhz 50    # a bitstream only
python -m examples.fpga.sweep --compare-sim     # every program on the board
```

### Updating Kathryn

The editable install links straight into `../Kathryn2/py/`, so what to do
after pulling or editing Kathryn depends on which half changed:

| what changed | what to do |
|---|---|
| Python side (`Kathryn2/py/kathryn/`) | nothing; imports pick it up immediately |
| Rust side (`Kathryn2/src/`, `Cargo.toml`) | rebuild: `cd ../Kathryn2 && maturin develop` with the venv active |
| `Kathryn2/pyproject.toml` | re-run `pip install -e ../Kathryn2` |

If `maturin develop` refuses because both `VIRTUAL_ENV` and `CONDA_PREFIX` are
set, run `env -u CONDA_PREFIX VIRTUAL_ENV=$PWD/.venv .venv/bin/maturin develop`.
A debug build only changes how fast the design elaborates; the emitted Verilog
is the same. Use `maturin develop --release` if elaboration feels slow.
