"""
Layer 6 diagnostic (prints only, no locked assertions yet). Reuses the
exact H1/M15 arrays from the locked test_zones_breakers.py bullish
fixture as the shared world (zone_low=9.9, zone_high=11.0, failed_at=19:00,
FVG fill at 19:45) and varies only candidate_ob/idm_price/h1_bos_event to
exercise the three Layer 6 conflict-resolution paths.
"""

import numpy as np
import pandas as pd
from conftest import _mk_df
from src.research import setups


def _build_shared_world():
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 9.5, 9.0, 10.8, 10.6, 10.7, 11.2, 11.3]
    h1_highs  = [10.2]*warmup_n + [11.0, 10.0, 9.6, 11.2, 10.95, 10.8, 11.3, 11.4, 11.5]
    h1_lows   = [9.8]*warmup_n  + [9.9, 9.3, 8.8, 8.9, 10.5, 10.55, 11.0, 11.1, 11.2]
    h1_closes = [10.0]*warmup_n + [10.5, 9.5, 9.0, 11.05, 10.6, 10.7, 11.2, 11.3, 11.4]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")

    m15_opens  = [12.5, 12.1, 11.2, 10.3, 10.5, 11.8, 12.3, 12.8]
    m15_highs  = [12.6, 12.2, 11.3, 10.6, 12.0, 12.5, 13.0, 13.2]
    m15_lows   = [12.0, 11.0, 10.2, 10.1, 10.4, 11.7, 12.2, 12.7]
    m15_closes = [12.1, 11.2, 10.3, 10.5, 11.8, 12.3, 12.8, 13.0]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 19:00")

    return h1_df, m15_df


def test_diag_layer6_breaker_wins():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)
    h1_df, m15_df = _build_shared_world()

    ps = setups.PairSetup("eurusd")
    ps.state = "ARMED"
    ps.model = "A"
    ps.candidate_ob = {"ob_low": 8.0, "ob_high": 9.0, "direction": "bullish"}
    ps.m15_bos_time = pd.Timestamp("2023-01-01 18:00:00", tz="UTC")
    ps.idm_price = 8.5
    ps.h1_bos_event = {
        "label": "BOS", "direction": "down",
        "time": pd.Timestamp("2023-01-01 17:00:00", tz="UTC"),
        "last_opposite_time": pd.Timestamp("2023-01-01 15:00:00", tz="UTC"),
        "last_opposite_price": 11.0,
    }

    print("\n--- DIAG breaker_wins ---")
    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(i, "state=", ps.state, "winner=", ps.winner, "resolved_at=", ps.resolved_at,
              "breaker_filled=", None if ps.breaker is None else ps.breaker.get("filled"),
              "breaker_fill_time=", None if ps.breaker is None else ps.breaker.get("fill_time"))
    assert ps.winner in (None, "ob", "breaker")


def test_diag_layer6_ob_wins():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)
    h1_df, m15_df = _build_shared_world()

    ps = setups.PairSetup("eurusd")
    ps.state = "ARMED"
    ps.model = "A"
    ps.candidate_ob = {"ob_low": 8.0, "ob_high": 11.5, "direction": "bullish"}
    ps.m15_bos_time = pd.Timestamp("2023-01-01 18:00:00", tz="UTC")
    ps.idm_price = 12.3
    ps.h1_bos_event = {
        "label": "BOS", "direction": "down",
        "time": pd.Timestamp("2023-01-01 17:00:00", tz="UTC"),
        "last_opposite_time": pd.Timestamp("2023-01-01 15:00:00", tz="UTC"),
        "last_opposite_price": 11.0,
    }

    print("\n--- DIAG ob_wins ---")
    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(i, "state=", ps.state, "winner=", ps.winner, "resolved_at=", ps.resolved_at,
              "touch_time=", ps.touch_time,
              "breaker_filled=", None if ps.breaker is None else ps.breaker.get("filled"))
    assert ps.winner in (None, "ob", "breaker")


def test_diag_layer6_no_breaker_regression():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)
    h1_df, m15_df = _build_shared_world()

    ps = setups.PairSetup("eurusd")
    ps.state = "ARMED"
    ps.model = "A"
    ps.candidate_ob = {"ob_low": 8.0, "ob_high": 11.5, "direction": "bullish"}
    ps.m15_bos_time = pd.Timestamp("2023-01-01 18:00:00", tz="UTC")
    ps.idm_price = 12.3
    ps.h1_bos_event = {
        "label": "BOS", "direction": "down",
        "time": pd.Timestamp("2023-01-01 17:00:00", tz="UTC"),
        "last_opposite_time": pd.NaT,
        "last_opposite_price": np.nan,
    }

    print("\n--- DIAG no_breaker_regression ---")
    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(i, "state=", ps.state, "winner=", ps.winner, "resolved_at=", ps.resolved_at,
              "touch_time=", ps.touch_time, "breaker=", ps.breaker)
    assert ps.winner in (None, "ob", "breaker")
    assert ps.breaker is None
