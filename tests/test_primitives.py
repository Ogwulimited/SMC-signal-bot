import pytest
import pandas as pd
import numpy as np
import random
from src.research.primitives import find_swings, detect_bos_choch, resample_to_tf, bars_available_at

def test_swing_d1_confirm():
    timestamps = pd.date_range("2023-01-01", periods=5, freq="1D", tz="UTC")
    df = pd.DataFrame({
        "timestamp": timestamps, "high": [1, 5, 10, 2, 1], "low": [0, 4, 9, 1, 0], "close": [1, 4, 9, 1, 0]
    })
    tf = pd.Timedelta("1D")
    swings = find_swings(df, n=1, tf=tf)
    assert len(swings) == 1
    assert swings.iloc[0]["confirm_time"] == pd.Timestamp("2023-01-05 00:00:00", tz="UTC")

def test_specific_sequence():
    timestamps = pd.date_range("2023-01-01", periods=9, freq="1h", tz="UTC")
    highs = [5, 10, 6, 7, 8, 6.5, 7, 8.6, 8.8]
    closes = [4.5, 9.5, 5.5, 6.5, 7.5, 6, 6.8, 8.4, 8.7]
    lows = [c - 1 for c in closes]
    df = pd.DataFrame({"timestamp": timestamps, "high": highs, "low": lows, "close": closes})
    
    swings = find_swings(df, n=1, tf=pd.Timedelta("1h"))
    events = detect_bos_choch(df, swings)
    
    assert len(events) == 1
    ev = events.iloc[0]
    assert ev["label"] == "INIT"
    assert ev["direction"] == "up"
    assert pd.Timestamp(ev["time"]) == timestamps[7]
    assert ev["broken_swing_price"] == 8.0

def test_bos_choch_sequence():
    """INIT(up) -> BOS(up) -> CHoCH(down)."""
    timestamps = pd.date_range("2023-01-01", periods=11, freq="1h", tz="UTC")
    highs =  [10, 8, 9, 12, 11, 11.5, 14, 13, 12.5, 11, 10]
    lows =   [8, 6, 7, 10, 9, 10, 12, 11, 11.2, 9, 8]
    closes = [9, 7, 10.5, 11, 10, 12.5, 13, 12, 12, 10, 9]
    df = pd.DataFrame({"timestamp": timestamps, "high": highs, "low": lows, "close": closes})
    
    swings = find_swings(df, n=1, tf=pd.Timedelta("1h"))
    events = detect_bos_choch(df, swings)
    
    assert events["label"].tolist() == ["INIT", "BOS", "CHoCH"]
    assert events["direction"].tolist() == ["up", "up", "down"]

def test_bos_choch_mirror():
    """INIT(down) -> BOS(down) -> CHoCH(up)."""
    timestamps = pd.date_range("2023-01-01", periods=12, freq="1h", tz="UTC")
    highs =  [10, 12, 11, 14, 13, 12, 10, 9, 10, 9, 10, 12]
    lows =   [8, 7, 6, 8, 7, 9, 4, 2.5, 3, 4, 5, 10]
    closes = [9, 8, 5, 10, 9, 8, 5, 4, 3, 5, 6, 11]
    df = pd.DataFrame({"timestamp": timestamps, "high": highs, "low": lows, "close": closes})
    
    swings = find_swings(df, n=1, tf=pd.Timedelta("1h"))
    events = detect_bos_choch(df, swings)
    
    assert events["label"].tolist() == ["INIT", "BOS", "CHoCH"]
    assert events["direction"].tolist() == ["down", "down", "up"]

def test_consumption_rule():
    timestamps = pd.date_range("2023-01-01", periods=8, freq="1h", tz="UTC")
    highs = [10, 8, 12, 15, 12, 16, 14, 12]
    closes = [9, 7, 11, 14, 11, 16, 13, 11]
    lows = [h - 1 for h in highs]
    df = pd.DataFrame({"timestamp": timestamps, "high": highs, "low": lows, "close": closes})
    
    swings = find_swings(df, n=1, tf=pd.Timedelta("1h"))
    events = detect_bos_choch(df, swings)
    
    assert len(events) == 1
    assert events.iloc[0]["broken_swing_price"] == 15.0

def test_dst_anchors():
    timestamps = pd.date_range("2023-03-11", "2023-03-14", freq="15min", tz="UTC")
    df = pd.DataFrame({"timestamp": timestamps, "open": 1, "high": 1, "low": 1, "close": 1})
    
    h4 = resample_to_tf(df, "4h", 7)
    for _, row in h4.iterrows():
        assert row["timestamp"].tz_convert("America/New_York").hour in (17, 21, 1, 5, 9, 13)
        
    d1 = resample_to_tf(df, "1D", 7)
    for _, row in d1.iterrows():
        assert row["timestamp"].tz_convert("America/New_York").hour == 17

def test_truncation():
    random.seed(42)
    np.random.seed(42)
    n = 500
    timestamps = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    prices = np.cumsum(np.random.randn(n) * 10)
    df = pd.DataFrame({"timestamp": timestamps, "high": prices + 5, "low": prices - 5, "close": prices, "open": prices})
    
    tf_m15 = pd.Timedelta("15m")
    full_swings = find_swings(df, n=2, tf=tf_m15)
    full_events = detect_bos_choch(df, full_swings)
    
    for cut in [random.randint(50, n - 20) for _ in range(100)]:
        df_cut = df.iloc[:cut].reset_index(drop=True)
        cut_swings = find_swings(df_cut, n=2, tf=tf_m15)
        cut_events = detect_bos_choch(df_cut, cut_swings)
        
        cutoff_time = df_cut["timestamp"].iloc[-1] + tf_m15
        if full_events.empty: continue
        expected = full_events[full_events["time"] <= cutoff_time].reset_index(drop=True)
        pd.testing.assert_frame_equal(expected, cut_events)

def test_truncation_h4_d1():
    random.seed(42)
    np.random.seed(42)
    n = 2000
    timestamps = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    prices = np.cumsum(np.random.randn(n) * 10)
    df = pd.DataFrame({"timestamp": timestamps, "high": prices + 5, "low": prices - 5, "close": prices, "open": prices})
    
    for rule, tf_str, n_swing in [("4h", "4h", 2), ("1D", "1D", 3)]:
        tf = pd.Timedelta(tf_str)
        full_resampled = resample_to_tf(df, rule, 7)
        full_swings = find_swings(full_resampled, n=n_swing, tf=tf)
        full_events = detect_bos_choch(full_resampled, full_swings)
        
        for cut in [random.randint(200, n - 200) for _ in range(50)]:
            df_cut = df.iloc[:cut].reset_index(drop=True)
            cut_resampled = resample_to_tf(df_cut, rule, 7)
            cut_swings = find_swings(cut_resampled, n=n_swing, tf=tf)
            cut_events = detect_bos_choch(cut_resampled, cut_swings)
            
            cutoff_time = cut_resampled["timestamp"].max()
            if full_events.empty: continue
            expected = full_events[full_events["time"] <= cutoff_time].reset_index(drop=True)
            pd.testing.assert_frame_equal(expected, cut_events)
