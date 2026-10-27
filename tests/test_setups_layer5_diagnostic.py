"""
Diagnostic-only: proves Layer 5 (sweep -> touch -> trigger) watch logic
behaves as expected, before locking exact assertions.

Does NOT re-derive arming (Layer 4) -- that's already locked separately.
Instead manually sets PairSetup to ARMED with known idm_price/candidate_ob,
then feeds crafted M15/H1 bars incrementally to observe state transitions.
"""

import pandas as pd
from conftest import _mk_df
from src.research import setups


def test_layer5_sweep_then_touch_diagnostic():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    # OB zone 8.0-9.0, IDM sits above it at 10.0 (correct geometry: IDM is
    # the shallower pullback low, OB is deeper, closer to L_base).
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

    print("\n=== LAYER 5: SWEEP THEN TOUCH DIAGNOSTIC ===")
    for i in range(len(m15_df)):
        ps.on_m15_close(h1_dummy, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(f"bar {i} ({m15_df['timestamp'].iloc[i]}): state={ps.state} "
              f"swept_time={ps.idm_swept_time} touch_time={ps.touch_time} "
              f"same_bar_ambiguous={ps.same_bar_ambiguous} fill1_price={ps.fill1_price}")

    assert True


def test_layer5_same_bar_ambiguous_diagnostic():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    # One bar's low (9.0) is both below IDM (10.0) AND at/below OB high (9.5)
    # -- sweep and touch collide on the same candle.
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

    print("\n=== LAYER 5: SAME-BAR AMBIGUOUS DIAGNOSTIC ===")
    for i in range(len(m15_df)):
        ps.on_m15_close(h1_dummy, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(f"bar {i} ({m15_df['timestamp'].iloc[i]}): state={ps.state} "
              f"same_bar_ambiguous={ps.same_bar_ambiguous} "
              f"last_cancel_reason={ps.last_cancel_reason}")

    assert True


def test_layer5_h1_close_through_cancel_diagnostic():
    tf_h1 = pd.Timedelta(hours=1)

    h1_df = _mk_df(
        opens=[10, 10, 7.0],
        highs=[11, 11, 7.2],
        lows=[9, 9, 6.8],
        closes=[10, 10, 7.5],  # bar index 2 closes below ob_low (8.0)
        freq="1h", start="2023-01-01",
    )
    pools = pd.DataFrame()

    ps = setups.PairSetup("eurusd")
    ps.bias = {"state": "bullish", "direction": "up", "time": pd.Timestamp("2022-12-01", tz="UTC"), "label": "BOS"}
    ps.zone = {"zone_low": 7.0, "zone_high": 12.0, "confirm_time": pd.Timestamp("2022-12-01", tz="UTC")}
    ps.candidate_ob = {"ob_low": 8.0, "ob_high": 9.0, "direction": "bullish"}
    ps.state = "ARMED"

    print("\n=== LAYER 5: H1 CLOSE-THROUGH CANCEL DIAGNOSTIC ===")
    for i in range(len(h1_df)):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        print(f"bar {i} ({h1_df['timestamp'].iloc[i]}): state={ps.state} "
              f"last_cancel_reason={ps.last_cancel_reason}")

    assert True
