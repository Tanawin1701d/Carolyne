# BlockManager — the base class every pipeline block inherits, and the reason
# a block and its hardware are TWO objects rather than one.
#
# Why it exists (2026-08-16):
# - Kathryn's `Module` runs its @init methods EAGERLY, inside __init__. Every
#   register, wire and Karray a module declares must therefore be known before
#   the module exists. A pipeline block cannot meet that: its shape comes from
#   an ISA description, from machine parameters, and sometimes from a neighbour
#   it has not been wired to yet. So the block is a plain Python object that
#   COLLECTS configuration, and `gen_hw()` is the single moment at which that
#   configuration becomes a Kathryn module.
# - That split is also what "we don't want to expose the kathryn module to the
#   user" means in practice: whoever assembles a pipeline names blocks, sets
#   their config and asks for hardware. The Kathryn import lives in the block
#   author's `_build_hw`, one level down.
#
# Decisions:
# - THE BASE CLASS OWNS THE LIFECYCLE, NOTHING ELSE. It does not model
#   configuration: how a block takes its settings — constructor arguments,
#   plain attributes, its own setters, a plan object handed in whole — is the
#   block's own business, and every block gets to invent what suits it. A
#   declared-config mechanism (`cfg()` descriptors, collected per subclass,
#   type-checked, completeness-checked at freeze) was written here on
#   2026-08-16 and removed the same day for exactly that reason; don't restore
#   it from git. The cost is real and accepted: `mark_fin_config()` cannot tell
#   whether a block is fully configured, so `_check_config()` is where a block
#   says what it knows about itself, and it is the ONLY completeness check.
# - THIS FILE IMPORTS NO KATHRYN. The base class owns the lifecycle, not the
#   hardware, and staying Kathryn-free means the state machine is testable with
#   no arena, no reset(), no emit. `gen_hw()` therefore does not type-check what
#   `build_hw()` returned beyond "not None" — the subclass is the one that
#   knows what a module is.
# - THREE states, from the sketch this file replaces:
#     WAIT4CONFIG -> CONFIGURED -> GEN_DONE
#   Both arrows run ONE WAY. Freezing is final: there is no reopen, so a block
#   is configured once and that is the configuration it keeps. Generating is
#   final for a harder reason — it declares hardware into the singleton arena,
#   `emit_verilog` consumes that arena, and a second `gen_hw()` would declare
#   the same block twice; undoing it means `kathryn.reset()`, which throws away
#   EVERY block, so it cannot be one block's decision.
# - The status is ADVISORY for a block's own settings, since nothing here
#   intercepts attribute writes — a blanket __setattr__ guard would fire inside
#   `build_hw`, where a block legitimately stores what it just built. A block
#   whose setters should refuse a late write tests `is_configured` in them.
# - `build_hw()` is PUBLIC, so `gen_hw()` is not the only way to reach it. A
#   caller that goes straight there gets a module with the status untouched, and
#   a second call declares the block twice in the arena — `gen_hw()` is the path
#   that keeps those two in step.
# - An Enum for the status, where the isa layer deliberately refuses enums for
#   ops and units. Same reasoning as `OperandRole`: those vocabularies are open
#   (an ISA may declare an op nobody anticipated), this one is closed by this
#   file. Nothing outside can invent a fourth lifecycle state.
# - `gen_hw()` returns None on purpose. It is a mutator ("change generate
#   module" in the sketch), and handing the module back would put Kathryn in the
#   caller's hands at exactly the point this class exists to avoid. The `hw`
#   property is the one door, for a block author wiring blocks together and for
#   whoever calls `set_top`.
# - `print_status()` prints, AND returns the same text, so a test or a report
#   can read it without capturing stdout.
#
# NOT here, on purpose: block hierarchy. A core containing a rename stage
# containing a RAT will want `mark_fin_config()` and `gen_hw()` to cascade to
# children, and this class has no children list. It is left out until the first
# block actually nests, because the cascade order (children first? parent's
# config feeding the child's?) is a decision the first real pipeline should
# make, not this file.

from __future__ import annotations

from enum import Enum
from typing import Optional


class BlockStatus(Enum):
    """Where a block is in its life. Closed set — see the header."""

    WAIT4CONFIG = "wait4config"     # taking configuration
    CONFIGURED  = "configured"      # frozen, waiting for gen_hw
    GEN_DONE    = "gen_done"        # hardware built; terminal


_BLURB = {
    BlockStatus.WAIT4CONFIG: "taking config",
    BlockStatus.CONFIGURED:  "config frozen, waiting for gen_hw()",
    BlockStatus.GEN_DONE:    "hardware generated (terminal)",
}


class BlockManager:
    """Base class for one pipeline block: config first, hardware on request.

    A subclass configures itself however it likes, cross-checks that config in
    `_check_config()`, and builds its hardware in `_build_hw()`. Nothing else
    about Kathryn reaches the caller.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        self._name   = name or type(self).__name__.lower()
        self._status = BlockStatus.WAIT4CONFIG
        self._hw     = None

    def __repr__(self) -> str:
        return (f"<{type(self).__name__} '{self._name}' "
                f"{self._status.name.lower()}>")

    # --- identity and state ---------------------------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> BlockStatus:
        return self._status

    @property
    def is_configured(self) -> bool:
        return self._status is not BlockStatus.WAIT4CONFIG

    @property
    def is_generated(self) -> bool:
        return self._status is BlockStatus.GEN_DONE

    @property
    def hw(self):
        """The generated Kathryn module.

        For a block author wiring blocks to each other, and for whoever calls
        `set_top` — not for the block's user, which is the whole point of the
        class (header).
        """
        if self._hw is None:
            raise RuntimeError(
                f"block '{self._name}': no hardware yet — call gen_hw() first "
                f"(status: {self._status.name})")
        return self._hw

    # --- lifecycle ------------------------------------------------------------
    def mark_fin_config(self) -> "BlockManager":
        """Freeze the configuration: WAIT4CONFIG -> CONFIGURED.

        Runs the block's own cross-checks first. This is the analogue of
        __post_init__ in the description layer — the moment a configuration that
        cannot work is supposed to fail, rather than deep inside gen_hw().
        """
        if self._status is not BlockStatus.WAIT4CONFIG:
            raise RuntimeError(
                f"block '{self._name}': already past config "
                f"({self._status.name})")
        self._check_config()
        self._status = BlockStatus.CONFIGURED
        return self

    def gen_hw(self) -> None:
        """CONFIGURED -> GEN_DONE: build the hardware, once.

        Returns nothing on purpose — read `.hw` if you are the one wiring it.
        """
        if self._status is BlockStatus.WAIT4CONFIG:
            raise RuntimeError(
                f"block '{self._name}': config is not frozen — call "
                f"mark_fin_config() before gen_hw()")
        if self._status is BlockStatus.GEN_DONE:
            raise RuntimeError(
                f"block '{self._name}': hardware was already generated; "
                f"building twice would declare it twice in the arena")
        hw = self.build_hw()
        if hw is None:
            raise RuntimeError(
                f"block '{self._name}': {type(self).__name__}.build_hw() "
                f"returned None — it must return the module it built")
        self._hw     = hw
        self._status = BlockStatus.GEN_DONE

    # --- subclass hooks -------------------------------------------------------
    def _check_config(self) -> None:
        """Cross-check this block's configuration. Override to say what it needs
        and how its settings relate ('depth must be a multiple of width');
        raise ValueError naming the block. Runs inside mark_fin_config(), and
        this is the ONLY completeness check there is — the base class does not
        model configuration, so it cannot know what 'complete' means."""

    def build_hw(self):
        """Build and return this block's Kathryn module. Override.

        This is the only place in a block where Kathryn is named. Everything the
        module needs is already on `self` — the config is frozen by now.
        """
        raise NotImplementedError(
            f"block '{self._name}': {type(self).__name__} must implement "
            f"build_hw() and return the module it built")

    def print_status(self) -> str:
        """Print where this block is in its life; return the text."""
        text = "\n".join([
            f"block '{self._name}' ({type(self).__name__}): "
            f"{self._status.name} — {_BLURB[self._status]}",
            f"  hardware: {'built' if self._hw is not None else 'not generated'}",
        ])
        print(text)
        return text
