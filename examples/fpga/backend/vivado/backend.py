# VivadoBackend — the emitted machine to a bitstream with AMD Vivado, in batch
# mode, from three templates:
#
#   core_wrapper.v.in      a Verilog wrapper around the emitted top that presents the
#                          HostBridge window as a BRAM_PORTA interface (so the block
#                          design connects it with one line) and hides the generated
#                          top name
#   build_params.tcl.in    every number and name the flow needs, as tcl variables
#   build_bitstream.tcl    the flow itself, static: project, block design, synth, impl,
#                          bitstream, reports, export
#
# The build directory is the whole state of one build: the filled templates,
# the Vivado project, the logs, and export/ with the .bit, the .hwh (same
# basename — PYNQ needs it), the host map and build_summary.txt.

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
from typing import Dict, Optional, Sequence

from examples.fpga.backend.base          import Bitstream, BitstreamRequest, BoardInfo
from examples.fpga.backend.fpga_backend  import FpgaBackend
from examples.fpga.backend.template      import fill_template
from examples.fpga.backend.vivado.report import SUMMARY_FILE, parse_build_summary
from examples.fpga.bridge import HOST_BRAM_CELL, RESET_GPIO_CELL

HERE           = pathlib.Path(__file__).resolve().parent
TEMPLATE_DIR   = HERE / "templates"
BOARDS_FILE    = HERE / "boards.json"

VIVADO_ENV     = "VIVADO"                                          # overrides the binary
DEFAULT_VIVADO = "/tools/Xilinx/Vivado/2023.2/bin/vivado"

FLOW_TCL       = "build_bitstream.tcl"
PARAMS_TCL     = "build_params.tcl"
WRAPPER_V      = "core_wrapper.v"
WRAPPER_MODULE = "carolyne_core_wrapper"
EXPORT_DIR     = "export"
HOST_MAP_FILE  = "host_map.json"
LOG_TAIL_LINES = 40


class VivadoBackend(FpgaBackend):
    """AMD Vivado, driven in batch mode."""

    name = "vivado"

    def __init__(self, vivado_bin: Optional[str] = None) -> None:
        self.vivado_bin = vivado_bin or os.environ.get(VIVADO_ENV) or DEFAULT_VIVADO
        self._version   : Optional[str] = None

    # --- the contract ---------------------------------------------------------------
    def boards(self) -> Dict[str, BoardInfo]:
        with open(BOARDS_FILE, "r", encoding="utf-8") as handle:
            table = json.load(handle)
        return {key: BoardInfo(key               = key,
                               part              = row["part"],
                               board_part        = row.get("board_part", ""),
                               board_connections = row.get("board_connections", ""),
                               ps_ip             = row.get("ps_ip", ""),
                               host_base_addr    = int(row["host_base_addr"], 0),
                               gpio_base_addr    = int(row["gpio_base_addr"], 0),
                               description       = row.get("description", ""))
                for key, row in table.items()}

    def describe(self) -> str:
        """`vivado -version`'s first line, read once; names the binary when it is not there."""
        if self._version is None:
            if not os.path.isfile(self.vivado_bin):
                self._version = f"vivado (not found at {self.vivado_bin})"
            else:
                done = subprocess.run([self.vivado_bin, "-version"], capture_output=True, text=True)
                self._version = (done.stdout.strip().splitlines() or ["vivado (unknown version)"])[0]
        return self._version

    def is_available(self) -> bool: return os.path.isfile(self.vivado_bin)

    def template_files(self) -> Sequence[pathlib.Path]:
        return sorted(TEMPLATE_DIR.iterdir())

    def build(self, request: BitstreamRequest, build_dir: pathlib.Path,
              log_path: Optional[pathlib.Path] = None) -> Bitstream:
        # step 1: make the build dir and export/, refuse early when vivado is missing
        build_dir  = pathlib.Path(build_dir)
        export_dir = build_dir / EXPORT_DIR
        build_dir .mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(exist_ok=True)
        if not self.is_available():
            raise RuntimeError(
                f"vivado not found at {self.vivado_bin} — set ${VIVADO_ENV} to the binary")

        # step 2: write the filled templates and the host map, then run the flow
        self.write_inputs(request, build_dir)
        request.host_map.write_json(str(export_dir / HOST_MAP_FILE))
        self.run_vivado(build_dir, log_path or build_dir / "vivado_stdout.log")

        # step 3: read the summary the tcl wrote; a --synth-only build has no .bit
        summary = export_dir / SUMMARY_FILE
        report  = parse_build_summary(summary) if summary.is_file() else {}
        bit     = export_dir / f"{request.name}.bit"
        hwh     = export_dir / f"{request.name}.hwh"
        if not request.synth_only and not (bit.is_file() and hwh.is_file()):
            raise RuntimeError(
                f"vivado finished but export/ holds no {bit.name} + {hwh.name} — see {build_dir}")

        # step 4: report what was built
        return Bitstream(bit_path      = str(bit),
                         hwh_path      = str(hwh),
                         host_map_path = str(export_dir / HOST_MAP_FILE),
                         build_dir     = str(build_dir),
                         reused        = False,
                         report        = report)

    # --- the pieces -------------------------------------------------------------------
    def write_inputs(self, request: BitstreamRequest, build_dir: pathlib.Path) -> None:
        """The filled wrapper and params, and the static flow, into the build dir."""
        hm    = request.host_map
        board = request.board
        fill_template(str(TEMPLATE_DIR / f"{WRAPPER_V}.in"), str(build_dir / WRAPPER_V),
                      {"{WRAPPER_MODULE}": WRAPPER_MODULE,
                       "{TOP_MODULE}"    : request.top_module,
                       "{ADDR_BITS}"     : hm.addr_bits,
                       "{WINDOW_BYTES}"  : hm.window_bytes})
        fill_template(str(TEMPLATE_DIR / f"{PARAMS_TCL}.in"), str(build_dir / PARAMS_TCL),
                      {"{PROJECT_NAME}"      : request.name,
                       "{PART}"              : board.part,
                       "{BOARD_PART}"        : board.board_part,
                       "{BOARD_CONNECTIONS}" : board.board_connections,
                       "{PS_IP}"             : board.ps_ip,
                       "{RTL_DIR}"           : tcl_path(request.rtl_dir),
                       "{WRAPPER_FILE}"      : tcl_path(build_dir / WRAPPER_V),
                       "{WRAPPER_MODULE}"    : WRAPPER_MODULE,
                       "{CLOCK_MHZ}"         : request.clock_mhz,
                       "{WINDOW_BYTES}"      : hm.window_bytes,
                       "{HOST_BASE_ADDR}"    : f"0x{board.host_base_addr:08X}",
                       "{GPIO_BASE_ADDR}"    : f"0x{board.gpio_base_addr:08X}",
                       "{HOST_BRAM_CELL}"    : HOST_BRAM_CELL,
                       "{RESET_GPIO_CELL}"   : RESET_GPIO_CELL,
                       "{EXPORT_DIR}"        : tcl_path(build_dir / EXPORT_DIR),
                       "{BIT_NAME}"          : request.name,
                       "{JOBS}"              : request.jobs,
                       "{SYNTH_ONLY}"        : int(request.synth_only)})
        shutil.copyfile(TEMPLATE_DIR / FLOW_TCL, build_dir / FLOW_TCL)

    def run_vivado(self, build_dir: pathlib.Path, log_path: pathlib.Path) -> None:
        """vivado in batch mode over the flow; a non-zero exit reports the log's tail."""
        argv = [self.vivado_bin, "-mode", "batch", "-nojournal",
                "-log", "vivado.log", "-source", FLOW_TCL, "-tclargs", PARAMS_TCL]
        with open(log_path, "w", encoding="utf-8") as log:
            done = subprocess.run(argv, cwd=str(build_dir), stdout=log, stderr=subprocess.STDOUT)
        if done.returncode:
            tail = pathlib.Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_TAIL_LINES:]
            raise RuntimeError(
                f"vivado exited with {done.returncode} in {build_dir}; the log ends:\n" + "\n".join(tail))


def tcl_path(path) -> str:
    """A path as tcl reads it: forward slashes, absolute."""
    return pathlib.Path(path).resolve().as_posix()
