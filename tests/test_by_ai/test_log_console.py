# The console capture: the bytes a program printed, in the C++ result shape.

from __future__ import annotations

from carolyne.debug.log.console import BANNER, ConsoleCapture


def test_characters_and_integers_land_in_order():
    console = ConsoleCapture()
    for byte in b"hi ":
        console.put_char(byte)
    console.put_int(16)
    console.put_char(ord("\n"))
    assert console.text == "hi 16\n"


def test_an_integer_word_reads_back_signed():
    console = ConsoleCapture()
    console.put_int(0xFFFFFFFF)
    console.put_char(ord(" "))
    console.put_int(0xFFFFFFFF, signed=False)
    assert console.text == "-1 4294967295"


def test_only_the_low_byte_of_a_character_word_is_printed():
    console = ConsoleCapture()
    console.put_char(0x41414141)
    assert console.text == "A"


def test_the_render_is_the_cycle_count_a_banner_and_the_bytes(tmp_path):
    console = ConsoleCapture()
    console.put_text("hello\n")
    assert console.render(2041) == f"2041\n{BANNER}\nhello\n"
    path = tmp_path / "out" / "console.txt"
    console.write(str(path), 2041)
    assert path.read_text() == console.render(2041)
