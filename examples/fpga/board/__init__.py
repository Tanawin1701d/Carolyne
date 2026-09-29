# The board: reaching it over ssh, putting a bitstream and programs on it, and
# running the driver there.
#
#   link.py           BoardLink: host, login, remote dir — from board.local.json (gitignored)
#   transport.py      SshTransport: ssh / scp as subprocesses, password via sshpass's environment
#   deploy.py         what goes where on the board: one directory per bitstream, runs/<program>/ under it
#   run_on_board.py   the script that runs there, under PYNQ's Python; imports only bridge/
#   board.example.json  the shape of board.local.json

from __future__ import annotations

from .deploy    import (BOARD_PACKAGE_FILES, OK_MARKER, RUN_SCRIPT, deploy_machine, deploy_programs,
                        remote_machine_dir, remote_spec_path, stage_board_package)
from .link      import BOARD_ENV, EXAMPLE_FILE, LOCAL_FILE, BoardLink, read_board_link
from .transport import SshTransport

__all__ = ["BoardLink", "read_board_link", "BOARD_ENV", "LOCAL_FILE", "EXAMPLE_FILE",
           "SshTransport",
           "deploy_machine", "deploy_programs", "remote_machine_dir", "remote_spec_path",
           "stage_board_package", "BOARD_PACKAGE_FILES", "RUN_SCRIPT", "OK_MARKER"]
