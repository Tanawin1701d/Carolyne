# BoardLink — how to reach the board: host, login, where to put files, how to
# start Python there. Read from a JSON file that is NOT in the repo
# (board.local.json, gitignored; board.example.json shows the shape) or from
# the file $CAROLYNE_BOARD names. The password never appears on a command line:
# transport.py passes it to sshpass through the environment.

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass
from typing import Optional

HERE         = pathlib.Path(__file__).resolve().parent
BOARD_ENV    = "CAROLYNE_BOARD"
LOCAL_FILE   = HERE / "board.local.json"
EXAMPLE_FILE = HERE / "board.example.json"

DEFAULT_REMOTE_DIR = "/root/jupyter_notebooks/calolyne_test"
DEFAULT_PRELUDE    = "source /etc/profile.d/pynq_venv.sh"     # PYNQ's Python, not the system one


@dataclass(frozen=True)
class BoardLink:
    """One board, as ssh reaches it."""

    host          : str
    user          : str           = "root"
    port          : int           = 22
    password      : Optional[str] = None       # sshpass; None = a key in ~/.ssh
    key_path      : Optional[str] = None       # an explicit key file, when not the default one
    remote_dir    : str           = DEFAULT_REMOTE_DIR
    python        : str           = "python3"
    shell_prelude : str           = DEFAULT_PRELUDE

    @property
    def target(self) -> str: return f"{self.user}@{self.host}"

    def describe(self) -> str:
        auth = "password" if self.password else (self.key_path or "default key")
        return f"{self.target}:{self.port} ({auth}) -> {self.remote_dir}"


def read_board_link(path: Optional[str] = None) -> BoardLink:
    """The link at `path`, else $CAROLYNE_BOARD's file, else board.local.json."""
    chosen = pathlib.Path(path or os.environ.get(BOARD_ENV) or LOCAL_FILE)
    if not chosen.is_file():
        raise RuntimeError(
            f"no board link file at {chosen} — copy {EXAMPLE_FILE.name} to {LOCAL_FILE.name} "
            f"beside it and fill in the board's login (the file is gitignored), or set ${BOARD_ENV}")
    with open(chosen, "r", encoding="utf-8") as handle:
        return BoardLink(**json.load(handle))
