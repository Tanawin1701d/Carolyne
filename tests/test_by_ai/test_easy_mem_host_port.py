# EasyMem's host write port: the outside agent's way in, beside the machine's
# one write port. What is pinned: it builds beside a machine writer, the
# one-machine-writer rule and its message are untouched, a second host writer
# is refused, and a memory that asks for none emits no trace of it.

from __future__ import annotations

import pytest
from kathryn import Module, build_model, emit_verilog, init, reset, wire

from carolyne.uarch.mem.common.mem_port import MemPortWrite
from carolyne.uarch.mem.easy_mem import EasyMem
from examples.o3.core.build import build_machine
from examples.o3.rv32im.config import gen_o3_rv32im_config


class Host(Module):
    """A memory with a machine writer, a reader, and whatever the test adds."""

    def __init__(self, banks: int, add_host: bool, second_host: bool = False, second_machine: bool = False):
        self.banks, self.add_host, self.second_host, self.second_machine = banks, add_host, second_host, second_machine
        super().__init__()

    @init
    def decl(self):
        self.mem   = EasyMem(4, self.banks, 4)
        self.read  = self.mem.add_read_port("load")
        self.store = self.mem.add_write_port("store")
        if self.add_host:
            self.host = self.mem.add_host_write_port("host")
        if self.second_host:
            self.mem.add_host_write_port("host2")
        if self.second_machine:
            self.mem.add_write_port("store2")
        self.go = wire(1, "go")
        self.mem.release_read_on(self.go)


def build(**kwargs) -> Host:
    reset()
    return build_model(Host(**kwargs))


@pytest.mark.parametrize("banks", [1, 2])
def test_a_host_writer_builds_beside_the_machine_writer(banks):
    host = build(banks=banks, add_host=True)
    assert isinstance(host.host, MemPortWrite)
    assert host.mem.write_ports == [host.store]                  # the host port is not a machine port
    assert host.mem.host_write_refused is not None
    assert host.host.addr_meta == host.mem.addr_meta


def test_a_host_writer_alone_builds_too():
    reset()

    class ReadOnlyMachine(Module):
        @init
        def decl(self):
            self.mem  = EasyMem(4, 2, 4)
            self.read = self.mem.add_read_port("lane0")
            self.host = self.mem.add_host_write_port()

    m = build_model(ReadOnlyMachine())
    assert m.mem.write_ports == []


def test_the_one_machine_writer_rule_and_its_message_are_untouched():
    with pytest.raises(ValueError, match="takes ONE write port .* 'store2' would be the second"):
        build(banks=1, add_host=True, second_machine=True)


def test_a_second_host_writer_is_refused():
    with pytest.raises(ValueError, match="already has a host write port"):
        build(banks=1, add_host=True, second_host=True)


def test_a_memory_that_asks_for_no_host_port_emits_no_trace_of_it(tmp_path):
    # the plain machine's Verilog is unchanged, so the sim's build cache stays warm
    reset()
    build_model(build_machine(gen_o3_rv32im_config(fe_lanes=2, commit_lanes=2)), debug=True)
    emit_verilog(str(tmp_path), "top")
    for path in tmp_path.glob("MODULE_EasyMem*.v"):
        assert "host" not in path.read_text()
