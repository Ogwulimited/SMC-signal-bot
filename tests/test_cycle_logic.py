"""Logic tests for the pullback cycle: lock rule, ceiling, orders, zones, mirror,
plus a synthetic run that checks no decision changes when the future is cut."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.research.engine import cycle as cy
from src.research.engine.poi import Poi
from src.research.lookahead_guard import Bar, DecisionLog

T0 = pd.Timestamp("2021-03-01 00:00", tz="UTC")
STEP = pd.Timedelta(minutes=15)
HOUR = pd.Timedelta(hours=1)


def mk_bar(i, o, h, l, c):
    t = T0 + i * STEP
    return Bar("M15", t, t + STEP, o, h, l, c)


def mk_ev(label, direction, bar, opp=None):
    return {"tf": "M15", "label": label, "direction": direction,
            "time": bar.close_time, "close": bar.close,
            "broken_swing_time": pd.NaT, "broken_swing_price": float("nan"),
            "last_opposite_time": bar.open_time if opp is not None else pd.NaT,
            "last_opposite_price": float("nan") if opp is None else float(opp),
            "known_at": bar.close_time}


def mk_rec(side="sell", zones=None):
    rec = cy.CycleRecorder(DecisionLog())
    ctx = cy._CTX[side]
    rec.bias["D1"].bias = ctx["bias"]
    rec.bias["H4"].bias = ctx["bias"]
    rec.state = cy.ARMED
    rec.ctx = ctx
    rec._freeze_zones = lambda: list(zones or [])
    for k in range(15):   # ATR = 1.0
        t = T0 - (20 - k) * HOUR
        rec.atr.on_bar_close(Bar("H1", t, t + HOUR, 100, 100.5, 99.5, 100))
    return rec


def go(rec, i, o, h, l, c, label=None, d=None, opp=None):
    bar = mk_bar(i, o, h, l, c)
    ev = mk_ev(label, d, bar, opp) if label else None
    rec._on_m15(bar, ev)
    return bar


def mk_poi(pid, origin, side, low, high, state="fresh", born=T0, tf="M15", candle=None):
    return Poi(id=pid, tf=tf, origin=origin, side=side, low=low, high=high,
               candle_time=candle if candle is not None else T0 - 2 * HOUR,
               swing_time=T0, born_time=born, shifted=0, cap_hit=False, state=state)


def fake_zone(low, high):
    return {"id": "Z", "tf": "H4", "poi": SimpleNamespace(state="fresh", id="Z"),
            "low": low, "high": high, "refined": False}


def start_pull(rec, ceiling=110.0):
    go(rec, 0, 100, 101, 99, 100, "CHoCH", "down", ceiling)
    assert rec.state == cy.PULL


# ---- lock rule ---------------------------------------------------------
def test_lock_bos_bos_then_ceiling_break_rearms():
    rec = mk_rec()
    start_pull(rec)
    assert rec._pb["ceiling"] == 110.0 and not rec._pb["locked"]
    go(rec, 1, 100, 100.2, 97.5, 98, "BOS", "down", 105.0)
    assert not rec._pb["locked"]
    go(rec, 2, 98, 98.2, 95.5, 96, "BOS", "down", 104.0)
    assert rec._pb["locked"]
    go(rec, 3, 96, 112, 95.8, 111)
    assert rec.state == cy.ARMED
    assert rec.pullbacks[0]["end_reason"] == "ceiling_break"


def test_lock_bos_then_choch_against():
    rec = mk_rec()
    start_pull(rec)
    go(rec, 1, 100, 100.2, 97.5, 98, "BOS", "down", 105.0)
    go(rec, 2, 98, 104.5, 97.9, 104, "CHoCH", "up", 103.0)
    assert rec._pb["locked"] and rec.state == cy.PULL


def test_choch_against_first_throws_ceiling_away():
    rec = mk_rec()
    start_pull(rec)
    go(rec, 1, 100, 104.5, 99.5, 104, "CHoCH", "up", 103.0)
    assert rec.state == cy.PULL
    assert rec._pb["ceiling"] is None and not rec._pb["locked"]
    go(rec, 2, 104, 105, 101, 102, "CHoCH", "down", 107.0)
    assert rec._pb["ceiling"] == 107.0


def test_temporary_ceiling_break_throws_attempt_away():
    rec = mk_rec()
    start_pull(rec)
    go(rec, 1, 100, 112, 99.5, 111)
    assert rec.state == cy.PULL
    assert rec._pb["ceiling"] is None
    assert rec.counts["attempt_failed_ceiling_break"] == 1


# ---- zone, scan, bias --------------------------------------------------
def _locked_pull(zones):
    rec = mk_rec(zones=zones)
    start_pull(rec)
    go(rec, 1, 100, 100.2, 97.5, 98, "BOS", "down", 105.0)
    go(rec, 2, 98, 98.2, 95.5, 96, "BOS", "down", 104.0)
    assert rec._pb["locked"]
    return rec


def test_zone_touch_then_scan_rearms_on_ceiling_break():
    rec = _locked_pull([fake_zone(90, 92)])
    go(rec, 3, 96, 97, 91.5, 93)
    assert rec.state == cy.SCAN
    assert rec.pullbacks[0]["end_reason"] == "zone"
    go(rec, 4, 93, 112, 92.5, 111)
    assert rec.state == cy.ARMED


def test_zone_touch_then_far_edge_break_goes_idle():
    rec = _locked_pull([fake_zone(90, 92)])
    go(rec, 3, 96, 97, 91.5, 93)
    go(rec, 4, 93, 93.5, 88, 89)
    assert rec.state == cy.IDLE


def test_bias_lost_ends_pullback():
    rec = mk_rec()
    start_pull(rec)
    rec.bias["D1"].bias = "bear"
    go(rec, 1, 100, 100.5, 99, 99.5)
    assert rec.state == cy.IDLE
    assert rec.pullbacks[0]["end_reason"] == "bias_lost"


# ---- breaker orders ----------------------------------------------------
def test_breaker_order_when_box_already_dead():
    rec = mk_rec()
    bar0 = mk_bar(0, 100, 100.5, 98.5, 99)
    brk = mk_poi("M15-1", "BOS", "buy", 100, 101, state="dead")
    rec.books["M15"].choch_breaker[bar0.close_time] = brk
    rec._on_m15(bar0, mk_ev("CHoCH", "down", bar0, 110.0))
    assert len(rec.orders) == 1
    o = rec.orders[0]
    assert o["side"] == "sell" and o["kind"] == "breaker"
    assert o["entry"] == 100.0
    assert o["stop"] == pytest.approx(101.2)
    assert o["end_time"] is None


def test_breaker_waits_until_box_dies():
    rec = mk_rec()
    bar0 = mk_bar(0, 100, 100.5, 98.5, 99)
    brk = mk_poi("M15-1", "BOS", "buy", 100, 101, state="fresh")
    rec.books["M15"].choch_breaker[bar0.close_time] = brk
    rec._on_m15(bar0, mk_ev("CHoCH", "down", bar0, 110.0))
    assert rec.orders == []
    brk.state = "dead"
    go(rec, 1, 99, 99.5, 98, 98.5)
    assert len(rec.orders) == 1
    assert rec.counts["breaker_late"] == 1


def test_breaker_not_placed_if_price_is_past_the_entry():
    rec = mk_rec()
    bar0 = mk_bar(0, 100, 101, 99, 100.5)
    brk = mk_poi("M15-1", "BOS", "buy", 100, 101, state="dead")
    rec.books["M15"].choch_breaker[bar0.close_time] = brk
    rec._on_m15(bar0, mk_ev("CHoCH", "down", bar0, 110.0))
    assert rec.orders == []
    assert rec.counts["breaker_entry_not_ahead"] == 1


def test_orders_cancelled_at_zone():
    rec = mk_rec(zones=[fake_zone(90, 92)])
    bar0 = mk_bar(0, 100, 100.5, 98.5, 99)
    brk = mk_poi("M15-1", "BOS", "buy", 100, 101, state="dead")
    rec.books["M15"].choch_breaker[bar0.close_time] = brk
    rec._on_m15(bar0, mk_ev("CHoCH", "down", bar0, 110.0))
    b1 = go(rec, 1, 99, 99, 91, 95)
    o = rec.orders[0]
    assert o["end_reason"] == "zone" and o["end_time"] == b1.close_time


def test_mirror_buy_context_breaker():
    rec = mk_rec("buy")
    bar0 = mk_bar(0, 100, 101.5, 99.5, 101)
    brk = mk_poi("M15-1", "BOS", "sell", 99, 100, state="dead")
    rec.books["M15"].choch_breaker[bar0.close_time] = brk
    rec._on_m15(bar0, mk_ev("CHoCH", "up", bar0, 90.0))
    assert len(rec.orders) == 1
    o = rec.orders[0]
    assert o["side"] == "buy" and o["entry"] == 100.0
    assert o["stop"] == pytest.approx(98.8)


# ---- OB orders ---------------------------------------------------------
def _ob_setup():
    rec = mk_rec()
    bar0 = mk_bar(0, 100, 100.5, 99, 99.5)
    box = mk_poi("M15-9", "CHoCH", "sell", 110, 112, born=bar0.close_time)
    rec.books["M15"].pois.append(box)
    rec._on_m15(bar0, mk_ev("CHoCH", "down", bar0, 112.0))
    go(rec, 1, 99.5, 99.6, 97, 98, "BOS", "down", 108.0)
    assert rec._pb["setups"][0]["ob"] == "wait_sweep"
    return rec


def test_ob_order_after_inducement_sweep():
    rec = _ob_setup()
    go(rec, 2, 98, 109, 97.5, 100)
    assert len(rec.orders) == 1
    o = rec.orders[0]
    assert o["kind"] == "ob" and o["side"] == "sell"
    assert o["entry"] == 110.0
    assert o["stop"] == pytest.approx(112.2)


def test_ob_skipped_when_sweep_bar_touches_box():
    rec = _ob_setup()
    go(rec, 2, 98, 111, 97.5, 100)
    assert rec.orders == []
    assert rec.counts["ob_same_bar"] == 1


# ---- D1 refinement -----------------------------------------------------
def _put_h4(rec, spec):
    for k, (o, h, l, c) in enumerate(spec):
        t = T0 + 4 * k * HOUR
        rec._h4[t] = Bar("H4", t, t + 4 * HOUR, o, h, l, c)
        rec._h4_times.append(t)


def test_d1_buy_zone_refines_to_right_colour_h4():
    rec = mk_rec()
    _put_h4(rec, [(105, 106, 103, 104), (104, 105, 102, 103), (101, 104, 100, 103),
                  (103, 105, 101, 104), (104, 106, 102, 105), (105, 106, 104, 105.5)])
    d1 = mk_poi("D1-1", "BOS", "buy", 100, 106, tf="D1", candle=T0)
    z = rec._refine(d1, True)
    assert z["refined"] and z["low"] == 102 and z["high"] == 105


def test_d1_sell_zone_refines_mirror():
    rec = mk_rec("buy")
    _put_h4(rec, [(100, 101, 99, 99.5), (99.5, 100, 98, 98.5), (98.5, 104, 98, 99),
                  (99, 101, 97, 98), (98, 100, 96, 97), (97, 99, 95, 96)])
    d1 = mk_poi("D1-2", "BOS", "sell", 95, 104, tf="D1", candle=T0)
    z = rec._refine(d1, False)
    assert z["refined"] and z["low"] == 98 and z["high"] == 104


def test_d1_without_h4_candles_keeps_d1_box():
    rec = mk_rec()
    d1 = mk_poi("D1-3", "BOS", "buy", 100, 106, tf="D1", candle=T0)
    z = rec._refine(d1, True)
    assert not z["refined"] and z["low"] == 100 and z["high"] == 106


# ---- synthetic run -----------------------------------------------------
def synth(n=26000, seed=3):
    """Synthetic M15 series that is closed on weekends like real forex:
    shut from Friday 17:00 to Sunday 17:00 New York time (so the US clock
    changes fall inside the gap, as they do on real data)."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    base = (100 + 4 * np.sin(2 * np.pi * t / (96 * 28)) + 1.5 * np.sin(2 * np.pi * t / (96 * 6))
            + 0.4 * np.sin(2 * np.pi * t / 50))
    close = base + rng.normal(0, 0.08, n)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.05, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.05, n))
    ts = pd.date_range("2020-01-05 22:00", periods=int(n * 1.5) + 700,
                       freq="15min", tz="UTC")
    ny = ts.tz_convert("America/New_York")
    wd = np.asarray(ny.day_of_week)
    hr = np.asarray(ny.hour)
    closed = ((wd == 4) & (hr >= 17)) | (wd == 5) | ((wd == 6) & (hr < 17))
    ts = ts[~closed][:n]
    assert len(ts) == n
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high,
                         "low": low, "close": close})


def test_synthetic_orders_are_well_formed():
    rec, log = cy.run_cycle(synth(), first_read=1)
    print("CYCLE SYNTH:", dict(rec.counts), "orders", len(rec.orders))
    keys = ("id", "pullback", "setup", "variant", "kind", "side", "placed_time", "entry",
            "stop", "stop_edge", "box_low", "box_high", "atr", "ceiling", "breaker_id",
            "anchor_id", "end_time", "end_reason")
    ids = set()
    for o in rec.orders:
        for k in keys:
            assert k in o
        assert o["id"] not in ids
        ids.add(o["id"])
        if o["side"] == "sell":
            assert o["stop"] > o["entry"]
            assert o["box_low"] <= o["entry"] <= o["box_high"]
        else:
            assert o["stop"] < o["entry"]
            assert o["box_low"] <= o["entry"] <= o["box_high"]
        assert o["end_time"] is None or o["end_time"] >= o["placed_time"]
    assert len([d for d in log.items if d.kind == "pb_order"]) == len(rec.orders)


def test_cut_does_not_change_earlier_decisions():
    m15 = synth()
    _, full = cy.run_cycle(m15, first_read=1)
    for frac in (0.45, 0.8):
        part = m15.iloc[:int(len(m15) * frac)].reset_index(drop=True)
        cut = part["timestamp"].iloc[-1] + STEP
        _, log = cy.run_cycle(part, first_read=1)
        a = [d.key() for d in full.items if d.time <= cut]
        b = [d.key() for d in log.items]
        assert a == b
