"""
Locks Fill 2 (conservative fill) behavior with exact-value assertions,
derived from real CI output (not hand-traced).

Fill 2 = the OPEN of the M15 bar immediately after the touch bar. It stays
pending (None) until that next bar has actually been observed -- modeling
real-world alert latency rather than assuming an instant fill at touch.
"""

import pandas as pd
from conftest import _mk_df
from src.research import setups


def test_fill2_resolves_on_next_bar():
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
        if i in (0, 1):
            assert ps.state == "ARMED"
            assert ps.fill2_price is None
        elif i in (2, 3):
            assert ps.state == "SWEPT"
            assert ps.fill2_price is None
        elif i == 4:
            assert ps.state == "TRIGGERED"
            assert ps.touch_time == pd.Timestamp("2023-01-01 01:15:00", tz="UTC")
            assert ps.fill1_price == 9.0
            assert ps.fill2_price is None  # next bar not yet observed
        elif i == 5:
            assert ps.state == "TRIGGERED"
            assert ps.fill1_price == 9.0
            assert ps.fill2_price == 5.0  # bar 5's open
