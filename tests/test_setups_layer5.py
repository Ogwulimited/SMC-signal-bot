"""
Locks Layer 5 (sweep -> touch -> trigger) watch logic with exact-value
assertions, derived from real CI output (not hand-traced).

Three scenarios:
1. Normal case: IDM swept, then a later bar touches the OB -> TRIGGERED.
2. Same-bar case: one bar both sweeps and touches -> abandoned, reset to IDLE.
3. H1 close-through case: while ARMED, an H1 close breaches the OB -> cancelled.
"""

import pandas as pd
from conftest import _mk_df
from src.research import setups


def test_layer5_sweep_then_touch():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    opens  = [20, 15, 9.5, 12, 8.5, 5]
    highs  = [21, 16, 10, 13, 9, 6]
    lows   = [20, 15, 9.5, 12, 8.5, 5]
    closes = [20, 15, 9.5, 12, 8.5, 5]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01 00:00")

    h1_dummy = _mk_df([10]*5, [11]*5, [9]*5, [10]*5, freq="1h", start="2023-01-01")

    ps = setups.PairSetup("eurusd")
    ps.state = "ARMED"
    ps.candidate_ob = {"ob_low": 8.0, "ob_high": 9.0, "direction": "bullish"}
    ps.model = "A"
    ps.m15_bos_time = pd.Timestamp("2023-01-01 00:15:00", tz="UTC")
    ps.idm_price = 10.0
    ps.idm_time = pd.Timestamp("2023-01-01 00:00:00", tz="UTC")

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_dummy, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        if i == 0:
            assert ps.state == "ARMED"
            assert pd.isna(ps.idm_swept_time)
            assert pd.isna(ps.touch_time)
        elif i == 1:
            assert ps.state == "ARMED"
            assert pd.isna(ps.idm_swept_time)
        elif i == 2:
            assert ps.state == "SWEPT"
            assert ps.idm_swept_time == pd.Timestamp("2023-01-01 00:45:00", tz="UTC")
            assert pd.isna(ps.touch_time)
        elif i == 3:
            assert ps.state == "SWEPT"
            assert ps.idm_swept_time == pd.Timestamp("2023-01-01 00:45:00", tz="UTC")
            assert pd.isna(ps.touch_time)
        elif i == 4:
            assert ps.state == "TRIGGERED"
            assert ps.idm_swept_time == pd.Timestamp("2023-01-01 00:45:00", tz="UTC")
            assert ps.touch_time == pd.Timestamp("2023-01-01 01:15:00", tz="UTC")
            assert ps.fill1_price == 9.0
        elif i == 5:
            # frozen once TRIGGERED -- no further recomputation
            assert ps.state == "TRIGGERED"
            assert ps.touch_time == pd.Timestamp("2023-01-01 01:15:00", tz="UTC")
            assert ps.fill1_price == 9.0


def test_layer5_same_bar_ambiguous():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    opens  = [20, 9.0, 12]
    highs  = [21, 9.2, 13]
    lows   = [20, 9.0, 12]
    closes = [20, 9.0, 12]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01 00:00")

    h1_dummy = _mk_df([10]*5, [11]*5, [9]*5, [10]*5, freq="1h", start="2023-01-01")

    ps = setups.PairSetup("eurusd")
    ps.state = "ARMED"
    ps.candidate_ob = {"ob_low": 8.0, "ob_high": 9.5, "direction": "bullish"}
    ps.model = "A"
    ps.m15_bos_time = pd.Timestamp("2023-01-01 00:15:00", tz="UTC")
    ps.idm_price = 10.0
    ps.idm_time = pd.Timestamp("2023-01-01 00:00:00", tz="UTC")

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_dummy, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        if i == 0:
            assert ps.state == "ARMED"
            assert ps.last_cancel_reason is None
        elif i in (1, 2):
            assert ps.state == "IDLE"
            assert ps.same_bar_ambiguous is None  # cleared by reset
            assert ps.last_cancel_reason == "same_bar_ambiguous"


def test_layer5_h1_close_through_cancel():
    tf_h1 = pd.Timedelta(hours=1)

    h1_df = _mk_df(
        opens=[10, 10, 7.0],
        highs=[11, 11, 7.2],
        lows=[9, 9, 6.8],
        closes=[10, 10, 7.5],
        freq="1h", start="2023-01-01",
    )
    pools = pd.DataFrame()

    ps = setups.PairSetup("eurusd")
    ps.bias = {"state": "bullish", "direction": "up", "time": pd.Timestamp("2022-12-01", tz="UTC"), "label": "BOS"}
    ps.zone = {"zone_low": 7.0, "zone_high": 12.0, "confirm_time": pd.Timestamp("2022-12-01", tz="UTC")}
    ps.candidate_ob = {"ob_low": 8.0, "ob_high": 9.0, "direction": "bullish"}
    ps.state = "ARMED"

    for i in range(len(h1_df)):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        if i in (0, 1):
            assert ps.state == "ARMED"
            assert ps.last_cancel_reason is None
        elif i == 2:
            assert ps.state == "IDLE"
            assert ps.last_cancel_reason == "h1_close_through_ob"
