"""
Diagnostic: does _model_b() inside find_inducement select an IDM swing
whose confirm_time falls AFTER armed_time?  If so, that's lookahead bias.

This test does NOT modify zones.py.  It calls find_inducement() on a
crafted fixture designed so _model_a() returns None (no M15 BOS) and
_model_b() has exactly one candidate IDM swing low whose bar index is
between s1 and the H1 BOS bar, but whose confirm_time is after armed_time.
"""

import pandas as pd
import numpy as np
from conftest import _mk_df
from src.research import zones


def _build_h1():
    """
    Bullish scenario.  n=2 for swings, tf_h1 = 1h.

    We need:
    - Enough warm-up bars for ATR (14+) and swing detection
    - A swing high (s1) with timestamp >= choch_time
    - A BOS bar (close > s1 price) some bars after s1's confirm_time
    - A swing low BETWEEN s1 and BOS by bar index, but whose confirm_time
      falls AFTER bos bar's close time (armed_time)

    With n=2, swing at bar i is confirmed at bar i+2, confirm_time = ts[i+2] + 1h.

    Layout (30 bars, 0-indexed):
    Bars 0-19: warm-up, gentle uptrend for ATR
    Bar 20: swing high candidate (s1) — needs high > bars 18,19,21,22
            confirm_time = ts[22] + 1h
    Bar 21-22: dip down (confirms bar 20 as swing high)
    Bar 23: we want this to be a swing low (IDM candidate)
            needs low < bars 21,22,24,25
            confirm_time = ts[25] + 1h
    Bar 25: BOS bar — close > s1 price
            armed_time = ts[25] + 1h
            So swing low at 23 has confirm_time = ts[25] + 1h = armed_time
            That's NOT strictly after.  We need confirm > armed.
            
    Fix: put swing low at bar 24 instead.
    Bar 24: swing low, needs low < bars 22,23,25,26
            confirm_time = ts[26] + 1h
    Bar 25: BOS bar, close > s1 price
            armed_time = ts[25] + 1h
            confirm_time of IDM = ts[26] + 1h > ts[25] + 1h ✓ LOOKAHEAD

    But wait — line 456 requires index < bos_idx.  bos_idx = 25.
    swing low at bar 24: index=24, 24 < 25 ✓
    And index > s1_idx: s1_idx=20, 24 > 20 ✓
    
    For n=2 swing low at bar 24: need low[24] < low[22], low[23], low[25], low[26]
    """
    n = 30
    # Warm-up: gentle uptrend
    opens  = [1.0 + i * 0.1 for i in range(20)]
    highs  = [o + 0.15 for o in opens]
    lows   = [o - 0.05 for o in opens]
    closes = [o + 0.08 for o in opens]

    # Bar 20: swing high (s1), high must dominate bars 18,19,21,22
    opens.append(3.00);  highs.append(5.00);  lows.append(2.90);  closes.append(3.10)
    # Bar 21: down
    opens.append(3.10);  highs.append(3.20);  lows.append(2.80);  closes.append(2.85)
    # Bar 22: down more (confirms bar 20 as swing high)
    opens.append(2.85);  highs.append(2.90);  lows.append(2.70);  closes.append(2.75)
    # Bar 23: slight recovery
    opens.append(2.75);  highs.append(2.85);  lows.append(2.65);  closes.append(2.80)
    # Bar 24: swing low (IDM candidate) — must have lowest low in window
    opens.append(2.80);  highs.append(2.82);  lows.append(2.00);  closes.append(2.50)
    # Bar 25: BOS bar — close must > s1 price (5.00)
    opens.append(2.50);  highs.append(5.50);  lows.append(2.45);  closes.append(5.20)
    # Bar 26: needed for swing low at 24 to be confirmed (bar 24+2=26)
    opens.append(5.20);  highs.append(5.30);  lows.append(5.00);  closes.append(5.10)
    # Bars 27-29: padding
    for i in range(3):
        opens.append(5.10 + i*0.1);  highs.append(5.25 + i*0.1)
        lows.append(5.00 + i*0.1);   closes.append(5.15 + i*0.1)

    return _mk_df(opens, highs, lows, closes, freq="1h", start="2023-03-01")


def _build_m15_empty():
    """M15 data that produces no swings / no BOS — forces _model_a() to return None."""
    n = 50
    flat = 3.0
    opens  = [flat] * n
    highs  = [flat + 0.001] * n
    lows   = [flat - 0.001] * n
    closes = [flat] * n
    return _mk_df(opens, highs, lows, closes, freq="15min", start="2023-03-01")


def test_model_b_lookahead_diagnostic():
    h1_df = _build_h1()
    m15_df = _build_m15_empty()
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    # choch_time: set before bar 20's timestamp so s1 can be found
    # (s1 needs timestamp >= choch_time)
    choch_time = h1_df["timestamp"].iloc[19] + tf_h1  # close time of bar 19

    # l_base_time: set early so _model_a scope is valid
    l_base_time = h1_df["timestamp"].iloc[15]

    # OB edges don't matter for this test, just need valid values
    ob_low, ob_high = 2.00, 2.50

    result = zones.find_inducement(
        h1_df, m15_df, tf_h1, tf_m15,
        choch_time=choch_time,
        l_base_time=l_base_time,
        ob_low=ob_low, ob_high=ob_high,
        direction="bullish"
    )

    print("\n=== MODEL B LOOKAHEAD DIAGNOSTIC ===")
    print(f"result is None: {result is None}")
    if result is not None:
        print(f"model: {result.get('model')}")
        print(f"idm_price: {result.get('idm_price')}")
        print(f"idm_time (confirm_time of IDM): {result.get('idm_time')}")
        print(f"armed_time: {result.get('armed_time')}")
        idm_t = result.get('idm_time')
        armed_t = result.get('armed_time')
        if idm_t is not None and armed_t is not None:
            print(f"idm_time > armed_time (LOOKAHEAD): {idm_t > armed_t}")
            print(f"idm_time == armed_time: {idm_t == armed_t}")
        print(f"swept_time: {result.get('swept_time')}")
        print(f"touch_time: {result.get('touch_time')}")
    else:
        print("find_inducement returned None — fixture may need adjustment")

    # Also print raw swings for debugging
    from src.research import primitives
    swings = primitives.find_swings(h1_df, 2, tf_h1)
    print(f"\nAll H1 swings:")
    print(swings.to_string())
    print(f"\nchoch_time used: {choch_time}")
    print(f"Bar 20 timestamp: {h1_df['timestamp'].iloc[20]}")
    print(f"Bar 24 timestamp: {h1_df['timestamp'].iloc[24]}")
    print(f"Bar 25 timestamp: {h1_df['timestamp'].iloc[25]}")
    print(f"Bar 26 timestamp: {h1_df['timestamp'].iloc[26]}")

    assert True  # diagnostic only
