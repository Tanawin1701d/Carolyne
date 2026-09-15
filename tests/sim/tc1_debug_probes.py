# The debug probes end to end: the toy pipeline's status words and its log
# table, read each cycle through the manifest the model exposed itself.
# Relations, not cycle numbers: a grant implies `go`, a stable `go` fixes every
# stage's word, `a` counts exactly on its granted cycles, and the log holds
# what B wrote.

from __future__ import annotations

import pathlib
import sys

from kathryn import build_model, emit_verilog, reset
from kathryn.sim.ksim import KSim

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

import cocotb_pool

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from carolyne.debug.sim import GRANTED, HELD, QUIET, RUNNING, STALL, WAITING   # noqa: E402
from tests.dbg_toy_model import CON_B_ZYNC_LEAF, CON_O_ZYNC_LEAF, LOG_ROWS, DbgToy                                       # noqa: E402

NAME       = "tc1_debug_probes"
RUN_CYCLES = 64
SETTLE     = 2          # cycles after a `go` edge before a stage's word is judged


# ---- build -------------------------------------------------------------------

def build(output_folder: str) -> None:
    reset()
    build_model(DbgToy(), debug=True)
    emit_verilog(output_folder)


# ---- simulation (cocotb) -----------------------------------------------------

async def reset_and_release(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.mrst.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.mrst.value = 0
    await RisingEdge(dut.clk)


def model_in_sim() -> DbgToy:
    # `convert` is the model probe's own method, so the model is rebuilt HERE, in
    # the simulator process — the same build, no emit; the manifest names the nets.
    reset()
    return build_model(DbgToy(), debug=True)


async def sample_cycles(dut, k: KSim) -> list:
    m       = model_in_sim()
    a, b, o = m.pipe_a.convert(k.pipe_a), m.pipe_b.convert(k.pipe_b), m.pipe_o.convert(k.pipe_o)
    log     = m.log_probe.convert(k.log_probe)
    rows    = []
    for _ in range(RUN_CYCLES):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        rows.append({"go"    : int(k.go.value),
                     "a"     : int(k.a.value),
                     "b"     : int(k.b.value),
                     "wr_ptr": int(k.wr_ptr.value),
                     "a_word": a.stage_status(b, CON_B_ZYNC_LEAF),
                     "b_word": b.pip_status(),
                     "b_stage": b.stage_status(o, CON_O_ZYNC_LEAF),
                     "b_leaf": b.leaf_status(CON_B_ZYNC_LEAF),
                     "o_leaf": o.leaf_status(CON_O_ZYNC_LEAF),
                     "b_park": b.parked,
                     "live"  : log.live_rows(valid="valid"),
                     "log"   : log.rows()})
    return rows


def stable_go(rows, idx: int) -> bool:
    return idx >= SETTLE and len({row["go"] for row in rows[idx - SETTLE:idx + 1]}) == 1


@cocotb.test()
async def check_status_words_follow_go(dut):
    """go=1: a/b RUNNING, o GRANTED; go=0: b HELD and its stage STALL (hold), a's leaf WAITING, a STALL, o QUIET."""
    k = KSim(dut)
    await reset_and_release(dut)
    rows = await sample_cycles(dut, k)
    for idx, row in enumerate(rows):
        dut._log.info(f"cyc {idx:3d} go={row['go']} a={row['a']:3d} b={row['b']:3d} a={row['a_word']:<7} "
                      f"b={row['b_word']:<7} b_stage={row['b_stage']:<7} b_leaf={row['b_leaf']:<7} o_leaf={row['o_leaf']:<7} "
                      f"park={row['b_park']} live={row['live']}")

    seen = set()
    for idx, row in enumerate(rows):
        if row["o_leaf"] == GRANTED:
            assert row["go"] == 1, f"cycle {idx}: the sink granted while go=0"
        if not stable_go(rows, idx):
            continue
        if row["go"]:
            assert row["o_leaf"] == GRANTED, f"cycle {idx}: {row}"
            assert row["b_word"] == RUNNING, f"cycle {idx}: {row}"
            assert row["b_stage"] == RUNNING, f"cycle {idx}: {row}"
            assert row["a_word"] == RUNNING, f"cycle {idx}: {row}"
        else:
            assert row["b_word"] == HELD,    f"cycle {idx}: {row}"
            assert row["b_stage"] == STALL,  f"cycle {idx}: {row}"     # its own arbiter is held
            assert row["b_leaf"] == WAITING, f"cycle {idx}: {row}"
            assert row["a_word"] == STALL,   f"cycle {idx}: {row}"
            assert row["o_leaf"] == QUIET,   f"cycle {idx}: {row}"     # cond-gated: no request while go=0
        seen.add(row["go"])
    assert seen == {0, 1}, f"both phases of go must be observed, saw {seen}"


@cocotb.test()
async def check_a_counts_exactly_on_its_grants(dut):
    """`a` steps by one in the cycle after its leaf on con_b is GRANTED, else holds."""
    k = KSim(dut)
    await reset_and_release(dut)
    rows = await sample_cycles(dut, k)
    for idx in range(len(rows) - 1):
        step = (rows[idx + 1]["a"] - rows[idx]["a"]) & 0xFF
        want = 1 if rows[idx]["b_leaf"] == GRANTED else 0
        assert step == want, f"cycle {idx}: a stepped {step} with leaf {rows[idx]['b_leaf']}"
    assert rows[-1]["a"] > 0, "a never counted"


@cocotb.test()
async def check_the_log_holds_what_b_wrote(dut):
    """Each grant of B's hop writes one row: valid set, data == the `b` that lands with it."""
    k = KSim(dut)
    await reset_and_release(dut)
    rows   = await sample_cycles(dut, k)
    writes = 0
    for idx in range(len(rows) - 1):
        before, after = rows[idx], rows[idx + 1]
        if after["wr_ptr"] == before["wr_ptr"]:
            assert after["log"] == before["log"], f"cycle {idx}: the log changed without a write"
            continue
        writes += 1
        assert after["wr_ptr"] == (before["wr_ptr"] + 1) % LOG_ROWS, f"cycle {idx}: wr_ptr jumped"
        written = after["log"][before["wr_ptr"]]
        assert written == {"valid": 1, "data": after["b"]}, f"cycle {idx}: row {before['wr_ptr']} = {written}"
        assert len(after["live"]) == min(writes, LOG_ROWS), f"cycle {idx}: live rows {after['live']}"
    assert writes >= LOG_ROWS, f"the log never wrapped: {writes} writes"


@cocotb.test()
async def check_the_sink_exposes_no_pip(dut):
    """con_o has no pip: no wait register, and pip_status refuses it."""
    k = KSim(dut)
    o = model_in_sim().pipe_o.convert(k.pipe_o)
    assert not o.has_pip and o.parked is None and o.leaf_count == 1
    try:
        o.pip_status()
    except ValueError:
        pass
    else:
        raise AssertionError("pip_status accepted an arb no pip masters")


# ---- register into the shared pool -------------------------------------------
cocotb_pool.register(NAME, build, __name__)
