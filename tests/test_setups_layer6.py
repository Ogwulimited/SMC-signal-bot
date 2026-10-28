"""
Locks Layer 6 (breaker as a separate, independent candidate riding the
same original H1 BOS event) conflict-resolution logic with exact-value
assertions, derived from real CI output.

Three scenarios, all sharing the same H1/M15 "world" (the locked
test_zones_breakers.py bullish fixture: zone_low=9.9, zone_high=11.0,
failed_at=19:00, FVG fill at 19:45), varying only candidate_ob/idm_price/
h1_bos_event:
1. Breaker wins: OB unreachable -> breaker fills first, freezes winner.
2. OB wins: OB reachable and resolves before the breaker's known fill time.
3. No-breaker regression: same OB timeline as #2, but h1_bos_event has no
   last_opposite_time -> detect_breakers rejects it entirely, breaker
   stays None throughout, confirming the OB-only path is unaffected.
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


def test_layer6_breaker_wins():
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

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        if i < 2:
            assert ps.state == "ARMED"
            assert ps.winner is None
            assert pd.isna(ps.resolved_at)
            assert ps.breaker["filled"] == False
        else:
            assert ps.state == "ARMED"
            assert ps.winner == "breaker"
            assert ps.resolved_at == pd.Timestamp("2023-01-01 19:45:00", tz="UTC")
            assert ps.breaker["filled"] == True
            assert ps.breaker["fill_time"] == pd.Timestamp("2023-01-01 19:45:00", tz="UTC")


def test_layer6_ob_wins():
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

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        if i == 0:
            assert ps.state == "SWEPT"
            assert ps.winner is None
            assert pd.isna(ps.touch_time)
            assert ps.breaker["filled"] == False
        else:
            assert ps.state == "TRIGGERED"
            assert ps.winner == "ob"
            assert ps.resolved_at == pd.Timestamp("2023-01-01 19:30:00", tz="UTC")
            assert ps.touch_time == pd.Timestamp("2023-01-01 19:30:00", tz="UTC")
            assert ps.breaker["filled"] == False


def test_layer6_no_breaker_regression():
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

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        assert ps.breaker is None
        if i == 0:
            assert ps.state == "SWEPT"
            assert ps.winner is None
        else:
            assert ps.state == "TRIGGERED"
            assert ps.winner == "ob"
            assert ps.resolved_at == pd.Timestamp("2023-01-01 19:30:00", tz="UTC")
