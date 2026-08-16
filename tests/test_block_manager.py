# BlockManager — the lifecycle every pipeline block inherits. The first test is
# the usage documentation: a block takes its config however it likes, freezes
# it, then generates. The rest pin the transitions that make the class worth
# having, notably "hardware cannot be generated from an unfrozen block" and "it
# cannot be generated twice".
#
# The base class models NO configuration on purpose (block_manager.py header),
# so the Rob below shows what a block does instead: plain constructor arguments
# and attributes, plus its own completeness check in _check_config.
#
# Note what these tests do NOT need: an arena, a reset(), an emit. That is the
# point of the base class importing no Kathryn — a fake build_hw stands in for
# the real one everywhere below.

import pytest

from carolyne.uarch.common import BlockManager, BlockStatus


class FakeHw:
    """Stands in for a Kathryn module: the base class only requires non-None."""

    def __init__(self, depth, width):
        self.depth, self.width = depth, width


class Rob(BlockManager):
    """Reorder buffer: retires at instruction granularity."""

    def __init__(self, name=None, depth=None, width=2):
        super().__init__(name)
        self.depth = depth              # the block's own config, its own way
        self.width = width

    def set_depth(self, depth):         # a setter that chooses to bite
        if self.is_configured:
            raise RuntimeError(f"block '{self.name}': depth set after freeze")
        self.depth = depth
        return self

    def _check_config(self):
        if self.depth is None:
            raise ValueError(f"block '{self.name}': depth was never set")
        if self.depth % self.width:
            raise ValueError(
                f"block '{self.name}': depth {self.depth} is not a multiple of "
                f"commit width {self.width}")

    def build_hw(self):
        return FakeHw(self.depth, self.width)


def test_a_block_is_configured_then_frozen_then_generated():
    rob = Rob("rob")
    assert rob.status is BlockStatus.WAIT4CONFIG and not rob.is_configured

    rob.depth = 64                          # a plain attribute: the block's call
    rob.mark_fin_config()
    assert rob.status is BlockStatus.CONFIGURED and rob.is_configured
    assert not rob.is_generated

    rob.gen_hw()
    assert rob.is_generated
    assert rob.hw.depth == 64 and rob.hw.width == 2


def test_the_base_class_models_no_configuration():
    # It never sees 'depth' — a block invents its own settings and its own way
    # of taking them, which is why the checks below live in Rob, not here.
    rob = Rob("rob", depth=32, width=4)
    assert (rob.depth, rob.width) == (32, 4)
    assert not hasattr(BlockManager, "depth")
    assert Rob().name == "rob"              # unnamed falls back to the class name


def test_completeness_is_the_blocks_own_check():
    # The base class cannot know what 'fully configured' means, so freezing a
    # block that never got a depth fails in Rob._check_config.
    rob = Rob("rob")
    with pytest.raises(ValueError, match="depth was never set"):
        rob.mark_fin_config()
    assert rob.status is BlockStatus.WAIT4CONFIG     # the failure left it open


def test_the_cross_check_runs_at_freeze():
    # The analogue of __post_init__ in the description layer: a configuration
    # that cannot work fails here, not deep inside build_hw.
    rob = Rob("rob", depth=63, width=2)
    with pytest.raises(ValueError, match="not a multiple"):
        rob.mark_fin_config()


def test_a_setter_may_choose_to_bite():
    # Nothing in the base class intercepts attribute writes — a blanket guard
    # would fire inside build_hw, where a block stores what it just built. A
    # block that wants its setters to refuse a late write tests is_configured.
    rob = Rob("rob", depth=64).mark_fin_config()
    with pytest.raises(RuntimeError, match="depth set after freeze"):
        rob.set_depth(32)
    rob.depth = 32                          # ...while a plain write still passes


def test_freezing_is_final_and_happens_once():
    rob = Rob("rob", depth=64).mark_fin_config()
    with pytest.raises(RuntimeError, match="already past config"):
        rob.mark_fin_config()               # there is no way back to WAIT4CONFIG


def test_hardware_needs_a_frozen_config_and_happens_once():
    rob = Rob("rob", depth=64)
    with pytest.raises(RuntimeError, match="config is not frozen"):
        rob.gen_hw()
    with pytest.raises(RuntimeError, match="no hardware yet"):
        _ = rob.hw

    rob.mark_fin_config()
    assert rob.gen_hw() is None             # a mutator: read .hw instead
    with pytest.raises(RuntimeError, match="already generated"):
        rob.gen_hw()                        # a second build would declare it twice


def test_generation_is_terminal():
    # The arena holds the hardware, and getting it back means kathryn.reset(),
    # which discards every block — so no transition leaves GEN_DONE.
    rob = Rob("rob", depth=64).mark_fin_config()
    rob.gen_hw()
    assert rob.status is BlockStatus.GEN_DONE
    with pytest.raises(RuntimeError, match="already past config"):
        rob.mark_fin_config()
    with pytest.raises(RuntimeError, match="already generated"):
        rob.gen_hw()


def test_a_block_must_build_something():
    class Empty(BlockManager):
        pass

    class Forgetful(BlockManager):
        def build_hw(self):
            FakeHw(1, 1)                    # built it, forgot to return it

    with pytest.raises(NotImplementedError, match="must implement build_hw"):
        Empty("empty").mark_fin_config().gen_hw()
    with pytest.raises(RuntimeError, match="returned None"):
        Forgetful("forgetful").mark_fin_config().gen_hw()


def test_gen_hw_is_the_path_that_keeps_status_and_hardware_in_step():
    # build_hw() is public, so a caller can reach it directly — and then the
    # block has a module nobody recorded. gen_hw() is what pairs the two.
    rob = Rob("rob", depth=64).mark_fin_config()
    loose = rob.build_hw()
    assert loose.depth == 64                # a real module...
    assert rob.status is BlockStatus.CONFIGURED     # ...that the block never saw
    with pytest.raises(RuntimeError, match="no hardware yet"):
        _ = rob.hw


def test_status_is_printable_and_returnable(capsys):
    rob  = Rob("rob", depth=64)
    text = rob.print_status()
    assert text == capsys.readouterr().out.rstrip("\n")
    assert "WAIT4CONFIG" in text and "not generated" in text
    assert "Rob" in text and "rob" in text

    rob.mark_fin_config()
    rob.gen_hw()
    assert "GEN_DONE" in rob.print_status()
    assert "built" in capsys.readouterr().out


def test_repr_says_where_the_block_is():
    rob = Rob("rob", depth=64)
    assert repr(rob) == "<Rob 'rob' wait4config>"
    assert repr(rob.mark_fin_config()) == "<Rob 'rob' configured>"
