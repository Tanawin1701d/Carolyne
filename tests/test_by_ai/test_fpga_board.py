# The board side without a board: the link file, the ssh/scp command lines, what
# is staged for upload, and the rendering of a board outcome into a RunResult.

from __future__ import annotations

import json
import pathlib
import re

import pytest

from carolyne.debug.log import ConsoleCapture
from examples.fpga.board import (BOARD_PACKAGE_FILES, EXAMPLE_FILE, RUN_SCRIPT, BoardLink, SshTransport,
                                 read_board_link, remote_machine_dir, stage_board_package)
from examples.fpga.board.deploy import HERE as BOARD_DIR
from examples.fpga.bridge import STOP_EXIT, TAG_PUTCHAR, TAG_PUTINT, HostRunOutcome
from examples.fpga.backend import Bitstream
from examples.fpga.result import run_result_of_outcome


# ---- the link ----------------------------------------------------------------------------

def test_the_example_link_file_reads_and_names_the_board():
    link = read_board_link(str(EXAMPLE_FILE))
    assert link.host == "192.168.1.149" and link.user == "root" and link.port == 22
    assert link.remote_dir.endswith("calolyne_test")
    assert link.target == "root@192.168.1.149"


def test_a_missing_link_file_says_what_to_create(tmp_path):
    with pytest.raises(RuntimeError, match="board.example.json.*board.local.json"):
        read_board_link(str(tmp_path / "nowhere.json"))


# ---- the command lines --------------------------------------------------------------------

def test_a_password_goes_through_sshpass_and_never_into_argv():
    link = BoardLink(host="10.0.0.5", password="s3cret")
    ssh  = SshTransport(link)
    argv = ssh.ssh_argv("ls")
    assert argv[:2] == ["sshpass", "-e"]
    assert "s3cret" not in " ".join(argv)
    assert ssh.env()["SSHPASS"] == "s3cret"
    assert argv[-2:] == ["root@10.0.0.5", "ls"]
    assert "-p" in argv and argv[argv.index("-p") + 1] == "22"


def test_a_key_login_uses_no_sshpass_and_scp_takes_a_capital_p():
    link = BoardLink(host="10.0.0.5", user="ubuntu", port=2222, key_path="/k/id")
    ssh  = SshTransport(link)
    assert ssh.ssh_argv("true")[0] == "ssh"
    scp = ssh.scp_argv(["a.bit", "b.hwh"], "ubuntu@10.0.0.5:/tmp/x/")
    assert scp[:2] == ["scp", "-r"]
    assert scp[scp.index("-P") + 1] == "2222"
    assert scp[scp.index("-i") + 1] == "/k/id"
    assert scp[-3:] == ["a.bit", "b.hwh", "ubuntu@10.0.0.5:/tmp/x/"]
    assert "SSHPASS" not in ssh.env()


# ---- what is deployed ----------------------------------------------------------------------

def test_the_staged_package_is_the_board_files_and_none_import_the_repo(tmp_path):
    staged = stage_board_package(tmp_path)
    assert sorted(p.name for p in staged.iterdir()) == sorted(BOARD_PACKAGE_FILES)
    for path in staged.iterdir():
        text = path.read_text()
        assert not re.search(r"^\s*(from|import)\s+(kathryn|cocotb|carolyne|examples)\b", text, re.M), path.name
    script = (BOARD_DIR / RUN_SCRIPT).read_text()
    assert not re.search(r"^\s*(from|import)\s+(kathryn|cocotb|carolyne|examples)\b", script, re.M)
    assert "from bridge import" in script


def test_the_remote_directory_is_named_by_the_bitstream_key():
    bitstream = Bitstream("/x/vivado/abcd1234abcd1234/export/carolyne_abcd1234abcd1234.bit", "/x/h.hwh",
                          "/x/m.json", "/x/vivado/abcd1234abcd1234", reused=True)
    assert remote_machine_dir("/root/jupyter_notebooks/calolyne_test/", bitstream) \
        == "/root/jupyter_notebooks/calolyne_test/abcd1234abcd1234"


# ---- the result -------------------------------------------------------------------------------

def test_a_board_outcome_renders_with_the_simulators_console_rules(tmp_path):
    entries = [(TAG_PUTCHAR, ord("h")), (TAG_PUTCHAR, ord("i")), (TAG_PUTINT, 0xFFFFFFFF), (TAG_PUTCHAR, 10)]
    outcome = HostRunOutcome(STOP_EXIT, 244, 0, entries, False, False, 0b111)
    result  = run_result_of_outcome(outcome, str(tmp_path))
    want    = ConsoleCapture()
    want.put_char(ord("h")); want.put_char(ord("i")); want.put_int(0xFFFFFFFF); want.put_char(10)
    assert result.console == want.text == "hi-1\n"
    assert result.stop_reason == "exit" and result.cycles == 244 and result.exit_code == 0
    assert (tmp_path / "console.txt").read_text().endswith("hi-1\n")
    assert json.loads(json.dumps(outcome.to_dict()))["console"][2] == [TAG_PUTINT, 0xFFFFFFFF]
