# deploy — what goes to the board, and where. One directory per bitstream
# under the link's remote_dir, named by the bitstream's cache key:
#
#   <remote_dir>/<key>/carolyne_<key>.bit  .hwh   host_map.json
#                     bridge/                       the driver package (stdlib + the pynq port)
#                     run_on_board.py               the script that runs the specs
#                     runs/<program>/               one uploaded run dir per program
#                     ok                            the bitstream landed whole
#
# The bridge package is STAGED locally first: only its stdlib files and the
# pynq port go, so the board never sees kathryn or cocotb imports.

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
from typing import Sequence

from examples.fpga.backend import Bitstream
from examples.fpga.board.transport import SshTransport
from examples.fpga.system import FpgaProgram

HERE                = pathlib.Path(__file__).resolve().parent
BRIDGE_SRC          = HERE.parent / "bridge"
BRIDGE_DIR_NAME     = "bridge"
BOARD_PACKAGE_FILES = ("__init__.py", "bridge_map.py", "bridge_driver.py", "bridge_driver_base.py",
                       "bridge_run_spec.py", "bridge_port_pynq.py")
RUN_SCRIPT          = "run_on_board.py"
RUNS_DIR            = "runs"
OK_MARKER           = "ok"


def bitstream_key_of(bitstream: Bitstream) -> str:
    """The cache key, which is the build dir's own name."""
    return pathlib.Path(bitstream.build_dir).name


def remote_machine_dir(remote_dir: str, bitstream: Bitstream) -> str:
    return f"{remote_dir.rstrip('/')}/{bitstream_key_of(bitstream)}"


def stage_board_package(stage_dir: pathlib.Path) -> pathlib.Path:
    """The bridge package as the board gets it, copied into stage_dir/bridge/."""
    target = pathlib.Path(stage_dir) / BRIDGE_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    for name in BOARD_PACKAGE_FILES:
        shutil.copyfile(BRIDGE_SRC / name, target / name)
    return target


def deploy_machine(transport: SshTransport, remote_dir: str, bitstream: Bitstream) -> str:
    """The bitstream, its map, the driver package and the run script; skipped when
    the board already holds them. Returns the remote machine directory."""
    remote = remote_machine_dir(remote_dir, bitstream)
    if transport.exists(f"{remote}/{OK_MARKER}"):
        return remote
    with tempfile.TemporaryDirectory() as stage:
        package = stage_board_package(pathlib.Path(stage))
        transport.upload([bitstream.bit_path, bitstream.hwh_path, bitstream.host_map_path,
                          str(package), str(HERE / RUN_SCRIPT)], remote)
    transport.check(f"touch {remote}/{OK_MARKER}")
    return remote


def deploy_programs(transport: SshTransport, remote_machine: str, programs: Sequence[FpgaProgram]) -> None:
    """Each program's run dir (its images and spec) under runs/<name>/."""
    for program in programs:
        transport.check(f"rm -rf {remote_machine}/{RUNS_DIR}/{program.name}")
        transport.upload([program.run_dir], f"{remote_machine}/{RUNS_DIR}")
        # the run dir lands under its own local name; rename to the program's when they differ
        local_name = os.path.basename(os.path.normpath(program.run_dir))
        if local_name != program.name:
            transport.check(f"mv {remote_machine}/{RUNS_DIR}/{local_name} {remote_machine}/{RUNS_DIR}/{program.name}")


def remote_spec_path(remote_machine: str, program: FpgaProgram) -> str:
    return f"{remote_machine}/{RUNS_DIR}/{program.name}/{os.path.basename(program.spec_path)}"
