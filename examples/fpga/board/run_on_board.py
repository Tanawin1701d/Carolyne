#!/usr/bin/env python3
# run_on_board.py — runs ON THE BOARD, under PYNQ's Python: load the overlay
# once, then run every bridge run spec named on the command line through the
# HostDriver, writing board_outcome.json beside each spec and printing one JSON
# line per program.
#
#     python3 run_on_board.py carolyne_<key>.bit runs/hello/bridge_run_spec.json [more specs]
#
# Everything it needs is in this directory: the bridge/ package (stdlib plus
# the pynq port) and the specs' images. It imports nothing from the repo.

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bridge import HostDriver, HostMap, read_bridge_run_spec, read_hex_words          # noqa: E402
from bridge.bridge_port_pynq import open_board_ports                                  # noqa: E402

OUTCOME_FILE = "board_outcome.json"
POLL_S       = 1e-3


def main(argv) -> int:
    if len(argv) < 3:
        print(__doc__ or "usage: run_on_board.py <bitstream.bit> <spec.json> [...]", file=sys.stderr)
        return 2
    bit_path, spec_paths = argv[1], argv[2:]

    from pynq import Overlay                     # here, so the usage message needs no pynq
    specs    = [read_bridge_run_spec(path) for path in spec_paths]
    host_map = HostMap.from_dict(specs[0].host_map)
    for spec in specs[1:]:
        if HostMap.from_dict(spec.host_map) != host_map:
            raise RuntimeError(f"{spec.name}: its host map differs from {specs[0].name}'s — not one machine")

    overlay     = Overlay(bit_path)
    port, reset = open_board_ports(overlay, host_map)
    driver      = HostDriver(port, reset, host_map)

    for spec, spec_path in zip(specs, spec_paths):
        banks   = [read_hex_words(path) for path in spec.instr_hex]
        data    = read_hex_words(spec.data_hex)
        outcome = asyncio.run(driver.run_program(banks, data, spec.cycle_limit, spec.timeout_s, POLL_S))
        out     = os.path.join(os.path.dirname(os.path.abspath(spec_path)), OUTCOME_FILE)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(outcome.to_dict(), handle, indent=1)
        print(json.dumps({"name": spec.name, "stop_reason": outcome.stop_reason,
                          "cycles": outcome.cycles, "exit_code": outcome.exit_code,
                          "console_entries": len(outcome.console)}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:                            # the whole traceback reaches the log on the PC
        traceback.print_exc()
        sys.exit(1)
