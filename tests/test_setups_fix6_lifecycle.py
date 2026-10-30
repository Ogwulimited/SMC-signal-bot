"""
tests/test_setups_fix6_lifecycle.py -- Fix #6 (persistent-hunting episode
lifecycle, anti-duplication guard, leg-ceiling full reset, cold-start guard).
"""

import pandas as pd
import pytest
from src.research import setups
from conftest import _mk_df


# ---------------------------------------------------------------------------
# Test A: reuses the locked Model A fixture through CHOCH_SEEN (also serves
# as a live regression check that Fix #6's leg-ceiling guard does NOT fire
# prematurely somewhere in bars 28-32 -- see flagged risk in chat), then
# exercises close_trade() -> _cycle_reset() and the duplication guard on
# three extra hand-checked-safe bars.
# ---------------------------------------------------------------------------

def _build_d1_fixture_a():
    return _mk_df(
        opens=[9.5, 8.5, 7.5, 5.0, 8.0, 9.0, 10.0, 15.0, 10.0, 9.0, 7.0, 24.5],
        highs=[10, 9, 8, 6, 11, 12, 13, 20, 13, 12, 11, 26],
        lows=[9, 8, 7, 3, 7, 8, 9, 9, 8, 7, 3, 24],
        closes=[9.5, 8.5, 7.5, 4.5, 9.0, 10.0, 11.0, 16.0, 11.0, 10.0, 8.0, 25.0],
        freq="1D", start="2023-01-01",
    )


def _build_h1_fixture_a_extended():
    opens  = [7.0]*14 + [7.0, 6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0,
                          9.9, 9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.0, 10.25] \
             + [10.6, 10.55, 10.6]
    highs  = [7.2]*14 + [7.1, 7.0, 7.0, 6.9, 7.5, 8.5, 9.5, 10.1, 10.2, 10.2,
                          10.0, 9.5, 9.6, 9.5, 9.8, 10.3, 10.5, 10.4, 10.35, 10.8] \
             + [10.65, 10.6, 10.65]
    lows   = [6.8]*14 + [6.5, 6.7, 6.75, 6.0, 6.1, 7.3, 8.3, 9.3, 9.8, 9.7,
                          9.0, 9.1, 9.2, 8.0, 8.4, 10.0, 10.1, 10.0, 10.0, 10.2] \
             + [10.5, 10.5, 10.55]
    closes = [7.0]*14 + [6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0, 9.9,
                          9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.2, 10.25, 10.7] \
             + [10.6, 10.55, 10.6]
    return _mk_df(opens, highs, lows, closes, freq="1h", start="2023-02-01")


def test_fix6_cycle_reset_and_duplication_guard():
    d1_df = _build_d1_fixture_a()
    h1_df = _build_h1_fixture_a_extended()

    d1_zones = pd.DataFrame(columns=["direction", "zone_low", "zone_high", "confirm_time", "invalidated_at"])
    d1_zones["confirm_time"] = pd.to_datetime(d1_zones["confirm_time"], utc=True)
    d1_zones["invalidated_at"] = pd.to_datetime(d1_zones["invalidated_at"], utc=True)

    h4_zones = pd.DataFrame([
        {"direction": "bullish", "zone_low": 10.0, "zone_high": 10.5,
         "confirm_time": pd.Timestamp("2023-01-05", tz="UTC"), "invalidated_at": pd.NaT},
    ])
    h4_zones["invalidated_at"] = pd.to_datetime(h4_zones["invalidated_at"], utc=True)

    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 9.0,
         "confirm_time": h1_df["timestamp"].iloc[5], "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)

    ps = setups.PairSetup("eurusd")
    ps.on_d1_close(d1_df, d1_zones, h4_zones, current_low=10.1, current_high=10.3)
    assert ps.state == "IDLE"

    for i in range(34):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        if i == 27:
            assert ps.state == "BOS_SEEN"
            assert ps.h1_bos_event["time"] == pd.Timestamp("2023-02-02 04:00:00", tz="UTC")
        elif i == 33:
            assert ps.state == "CHOCH_SEEN"
            assert ps.h1_choch_event["time"] == pd.Timestamp("2023-02-02 10:00:00", tz="UTC")

    assert ps.state == "CHOCH_SEEN"
    bos1_time = ps.h1_bos_event["time"]
    ceiling_before = ps.leg_ceiling_price

    ps.close_trade()

    assert ps.state == "EPISODE"
    assert ps.last_traded_bos_time == bos1_time
    assert ps.leg_ceiling_price == ceiling_before
    assert ps.h1_bos_event is None
    assert ps.h1_choch_event is None
    assert ps.candidate_ob is None
    assert ps.model is None
    assert ps.m15_bos_time is None
    assert ps.idm_price is None
    assert ps.idm_time is None
    assert ps.idm_swept_time is None
    assert ps.touch_time is None
    assert ps.same_bar_ambiguous is None
    assert ps.invalid_h1_close_through is None
    assert ps.fill1_price is None
    assert ps.fill2_price is None
    assert ps.breaker is None
    assert ps.winner is None
    assert pd.isna(ps.resolved_at)

    for i in range(34, 37):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        assert ps.state == "EPISODE"
        assert ps.h1_bos_event is None


# ---------------------------------------------------------------------------
# Test B: injected state starts mid-leg in EPISODE (zone-touch gate already
# skipped, as in a real post-cycle-reset scenario), with a sentinel
# leg_ceiling_price far from all prices in the fixture to isolate the
# BOS -> CHoCH detection path from the ceiling-cross path.
# ---------------------------------------------------------------------------

def test_fix6_fresh_cycle_without_zone_touch():
    h1_df = _mk_df(
        opens=[10.0, 10.0, 10.0, 7.5, 7.4, 7.45, 6.5, 6.4, 5.8, 5.75,
               5.8, 5.2, 5.6, 6.3, 6.2, 6.1],
        highs=[10.2, 10.1, 10.1, 7.6, 7.5, 7.5, 6.6, 6.5, 5.9, 5.85,
               6.3, 5.8, 6.5, 6.4, 6.3, 6.8],
        lows=[9.8, 9.9, 7.0, 7.3, 7.35, 6.0, 6.3, 5.5, 5.6, 5.65,
              5.0, 5.1, 5.5, 6.1, 6.0, 6.0],
        closes=[10.0, 10.0, 7.5, 7.4, 7.45, 6.5, 6.4, 5.8, 5.75, 5.8,
                5.2, 5.6, 6.3, 6.2, 6.1, 6.7],
        freq="1h", start="2023-06-01",
    )

    pools = pd.DataFrame(columns=["pool_type", "side", "pool_price", "confirm_time", "swept_time", "expires_at"])
    pools["confirm_time"] = pd.to_datetime(pools["confirm_time"], utc=True)
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)

    ps = setups.PairSetup("eurusd")
    ps.bias = {"state": "bullish", "direction": "up",
               "time": pd.Timestamp("2023-05-01", tz="UTC"), "label": "BOS"}
    ps.zone = {"timeframe": "H4", "zone_low": 0.0, "zone_high": 0.0,
               "confirm_time": pd.Timestamp("2023-05-01", tz="UTC")}
    ps.state = "EPISODE"
    ps.last_traded_bos_time = pd.NaT
    ps.leg_ceiling_price = 999.0

    expected_states = ["EPISODE"] * 10 + ["BOS_SEEN"] * 5 + ["CHOCH_SEEN"]

    for i in range(16):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        assert ps.state == expected_states[i], f"bar {i}: expected {expected_states[i]}, got {ps.state}"
        assert ps.leg_ceiling_price == pytest.approx(999.0)

    assert ps.h1_bos_event["time"] == pd.Timestamp("2023-06-01 11:00:00", tz="UTC")
    assert ps.h1_bos_event["direction"] == "down"
    assert ps.h1_bos_event["label"] == "BOS"
    assert ps.h1_choch_event["time"] == pd.Timestamp("2023-06-01 16:00:00", tz="UTC")
    assert ps.h1_choch_event["direction"] == "up"
    assert ps.h1_choch_event["label"] == "CHoCH"


# ---------------------------------------------------------------------------
# Test C: fresh 3-bar fixture, injected mid-leg state with a known ceiling.
# Bar 3's close crosses the ceiling -> full reset, independent of BOS/CHoCH
# detection entirely (fires before that code path is ever reached).
# ---------------------------------------------------------------------------

def test_fix6_leg_ceiling_cross_triggers_full_reset():
    h1_df = _mk_df(
        opens=[9.5, 9.2, 10.8],
        highs=[9.6, 9.7, 11.2],
        lows=[8.8, 9.0, 10.7],
        closes=[9.0, 9.6, 11.1],
        freq="1h", start="2023-07-01",
    )
    tf_h1 = pd.Timedelta(hours=1)

    ps = setups.PairSetup("eurusd")
    ps.bias = {"state": "bullish", "direction": "up",
               "time": pd.Timestamp("2023-05-01", tz="UTC"), "label": "BOS"}
    ps.zone = {"timeframe": "H4", "zone_low": 0.0, "zone_high": 0.0,
               "confirm_time": pd.Timestamp("2023-05-01", tz="UTC")}
    ps.state = "BOS_SEEN"
    ps.leg_ceiling_price = 10.0
    ps.last_traded_bos_time = pd.Timestamp("2023-06-01", tz="UTC")
    ps.h1_bos_event = pd.Series({
        "time": pd.Timestamp("2023-06-15", tz="UTC"),
        "last_opposite_price": 10.0,
        "direction": "down",
        "label": "BOS",
    })

    for i in range(2):
        ps.on_h1_close(h1_df.iloc[:i + 1], None, tf_h1)
        assert ps.state == "BOS_SEEN", f"bar {i}: expected BOS_SEEN, got {ps.state}"

    ps.on_h1_close(h1_df.iloc[:3], None, tf_h1)
    assert ps.state == "IDLE"
    assert ps.leg_ceiling_price is None
    assert pd.isna(ps.last_traded_bos_time)
    assert ps.h1_bos_event is None


# ---------------------------------------------------------------------------
# Test D: cold-start guard. First countertrend BOS seen (bar 10) carries a
# NaN last_opposite_price -- leg_ceiling_price must stay None and the check
# must keep retrying on every later h1_bos_event update, until bar 22's new
# down-BOS finally carries a real value (6.5) and locks it in.
# ---------------------------------------------------------------------------

def test_fix6_cold_start_ceiling_guard():
    h1_df = _mk_df(
        opens=[10.0, 10.0, 10.0, 7.5, 7.4, 7.45, 6.5, 6.4, 5.8, 5.75, 5.8,
               5.2, 5.6, 6.3, 6.2, 6.1, 6.0, 5.7, 5.3, 4.9, 5.4, 5.2, 5.1],
        highs=[10.2, 10.1, 10.1, 7.6, 7.5, 7.5, 6.6, 6.5, 5.9, 5.85, 6.3,
               5.8, 6.5, 6.4, 6.3, 6.2, 6.1, 5.8, 5.4, 5.6, 5.5, 5.3, 5.2],
        lows=[9.8, 9.9, 7.0, 7.3, 7.35, 6.0, 6.3, 5.5, 5.6, 5.65, 5.0,
              5.1, 5.5, 6.1, 6.0, 5.9, 5.6, 5.2, 4.8, 4.85, 5.1, 5.0, 3.0],
        closes=[10.0, 10.0, 7.5, 7.4, 7.45, 6.5, 6.4, 5.8, 5.75, 5.8, 5.2,
                5.6, 6.3, 6.2, 6.1, 6.0, 5.7, 5.3, 4.9, 5.4, 5.2, 5.1, 3.5],
        freq="1h", start="2023-09-01",
    )

    pools = pd.DataFrame(columns=["pool_type", "side", "pool_price", "confirm_time", "swept_time", "expires_at"])
    pools["confirm_time"] = pd.to_datetime(pools["confirm_time"], utc=True)
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)

    ps = setups.PairSetup("eurusd")
    ps.bias = {"state": "bullish", "direction": "up",
               "time": pd.Timestamp("2023-08-01", tz="UTC"), "label": "BOS"}
    ps.zone = {"timeframe": "H4", "zone_low": 0.0, "zone_high": 0.0,
               "confirm_time": pd.Timestamp("2023-08-01", tz="UTC")}
    ps.state = "EPISODE"
    ps.last_traded_bos_time = pd.NaT
    ps.leg_ceiling_price = None

    expected_states = ["EPISODE"] * 10 + ["BOS_SEEN"] * 13

    for i in range(23):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        assert ps.state == expected_states[i], f"bar {i}: expected {expected_states[i]}, got {ps.state}"

        if i < 10:
            assert ps.h1_bos_event is None
            assert ps.leg_ceiling_price is None
        elif i <= 21:
            assert ps.h1_bos_event["time"] == pd.Timestamp("2023-09-01 11:00:00", tz="UTC")
            assert pd.isna(ps.h1_bos_event["last_opposite_price"])
            assert ps.leg_ceiling_price is None
        else:  # i == 22
            assert ps.h1_bos_event["time"] == pd.Timestamp("2023-09-01 23:00:00", tz="UTC")
            assert ps.h1_bos_event["last_opposite_price"] == pytest.approx(6.5)
            assert ps.leg_ceiling_price == pytest.approx(6.5)
