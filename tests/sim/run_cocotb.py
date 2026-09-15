#!/usr/bin/env python3
# Simulate Carolyne's tc*.py models through Kathryn2's cocotb pool.
#
#   .venv/bin/python tests/sim/run_cocotb.py [simulator [tc_name ...]]
#
# `simulator` defaults to "icarus"; "verilator" also works. Output lands under
# generated/sim/<case>/ (one VCD per @cocotb.test()). The pool is Kathryn2's
# (test/cocotb_pool); KATHRYN2_DIR overrides the sibling-repo path from
# .claude/peer.md.

from __future__ import annotations

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent            # tests/sim
REPO = HERE.parents[1]                                    # Carolyne
KATHRYN2 = pathlib.Path(os.environ.get("KATHRYN2_DIR", REPO.parent / "Kathryn2"))

sys.path.insert(0, str(KATHRYN2 / "test"))                # find cocotb_pool

import cocotb_pool  # noqa: E402

if __name__ == "__main__":
    sim    = sys.argv[1] if len(sys.argv) > 1 else "icarus"
    names  = sys.argv[2:] or None
    cocotb_pool.configure(model_dir=HERE, out_root=REPO / "generated" / "sim", extra_pythonpath=(REPO,))
    results = cocotb_pool.discover_and_run(sim, names)
    if any(r.status not in ("PASS", "SKIP") for r in results):
        sys.exit(1)
