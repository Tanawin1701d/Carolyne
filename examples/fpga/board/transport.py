# SshTransport — files and commands to the board over ssh/scp, as subprocesses.
# No Python ssh library: the tools are on every machine that has Vivado, a
# password goes through sshpass's environment (never argv), and a remote
# command's exit code and output come back as they are.

from __future__ import annotations

import os
import shlex
import subprocess
from typing import List, Optional, Sequence

from examples.fpga.board.link import BoardLink

CONNECT_TIMEOUT_S = 10


class SshTransport:
    """ssh / scp to one BoardLink."""

    def __init__(self, link: BoardLink, connect_timeout_s: int = CONNECT_TIMEOUT_S) -> None:
        self.link              = link
        self.connect_timeout_s = connect_timeout_s

    # --- argv builders (pure, so a test can read them) -----------------------------------
    def _prefix(self) -> List[str]:
        return ["sshpass", "-e"] if self.link.password else []

    def _options(self, port_flag: str) -> List[str]:
        options = ["-o", "StrictHostKeyChecking=accept-new",
                   "-o", f"ConnectTimeout={self.connect_timeout_s}",
                   port_flag, str(self.link.port)]
        if self.link.key_path:
            options += ["-i", self.link.key_path]
        return options

    def ssh_argv(self, remote_command: str) -> List[str]:
        return [*self._prefix(), "ssh", *self._options("-p"), self.link.target, remote_command]

    def scp_argv(self, sources: Sequence[str], destination: str, recursive: bool = True) -> List[str]:
        flags = ["-r"] if recursive else []
        return [*self._prefix(), "scp", *flags, *self._options("-P"), *sources, destination]

    def env(self) -> dict:
        env = dict(os.environ)
        if self.link.password:
            env["SSHPASS"] = self.link.password
        return env

    # --- doing it ------------------------------------------------------------------------------
    def run(self, remote_command: str, timeout_s: Optional[float] = None) -> subprocess.CompletedProcess:
        """Run a command on the board; the caller reads returncode/stdout/stderr."""
        return subprocess.run(self.ssh_argv(remote_command), env=self.env(),
                              capture_output=True, text=True, timeout=timeout_s)

    def check(self, remote_command: str, timeout_s: Optional[float] = None) -> str:
        """Run and insist on success; returns stdout."""
        done = self.run(remote_command, timeout_s)
        if done.returncode:
            raise RuntimeError(
                f"on {self.link.target}: `{remote_command}` exited {done.returncode}\n"
                f"{done.stdout[-2000:]}{done.stderr[-2000:]}")
        return done.stdout

    def upload(self, local_paths: Sequence[str], remote_dir: str) -> None:
        self.check(f"mkdir -p {shlex.quote(remote_dir)}")
        done = subprocess.run(self.scp_argv([str(p) for p in local_paths], f"{self.link.target}:{remote_dir}/"),
                              env=self.env(), capture_output=True, text=True)
        if done.returncode:
            raise RuntimeError(f"scp to {self.link.target}:{remote_dir} failed\n{done.stderr[-2000:]}")

    def download(self, remote_path: str, local_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        done = subprocess.run(self.scp_argv([f"{self.link.target}:{remote_path}"], local_path, recursive=False),
                              env=self.env(), capture_output=True, text=True)
        if done.returncode:
            raise RuntimeError(f"scp from {self.link.target}:{remote_path} failed\n{done.stderr[-2000:]}")

    def exists(self, remote_path: str) -> bool:
        return self.run(f"test -e {shlex.quote(remote_path)}").returncode == 0
