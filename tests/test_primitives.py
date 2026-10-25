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
    
    tf = pd.Timedelta("1h")
    swings = find_swings(df, n=1, tf=tf)
    events = detect_bos_choch(df, swings, tf)
    
    assert len(events) == 1
    ev = events.iloc[0]
    assert ev["label"] == "INIT"
    assert ev["direction"] == "up"
    assert pd.Timestamp(ev["time"]) == timestamps[7] + tf
    assert ev["broken_swing_price"] == 8.0

def test_bos_choch_sequence():
    """INIT(up) -> BOS(up) -> CHoCH(down). Pre-verified arrays."""
    timestamps = pd.date_range("2023-01-01", periods=8, freq="1h", tz="UTC")
    highs = [10, 14, 11, 15, 13, 17, 14, 10]
    lows = [8, 9, 8, 8.5, 9, 9, 8, 7.5]
    closes = [9, 10, 9, 15, 12, 16, 9, 7.8]
    df = pd.DataFrame({"timestamp": timestamps, "high": highs, "low": lows, "close": closes})
    
    tf = pd.Timedelta("1h")
    swings = find_swings(df, n=1, tf=tf)
    events = detect_bos_choch(df, swings, tf)
    
    assert events["label"].tolist() == ["INIT", "BOS", "CHoCH"]
    assert events["direction"].tolist() == ["up", "up", "down"]

def test_bos_choch_mirror():
    """INIT(down) -> BOS(down) -> CHoCH(up). Pre-verified arrays."""
    timestamps = pd.date_range("2023-01-01", periods=8, freq="1h", tz="UTC")
    highs = [17, 16, 17, 16.5, 16, 16, 17, 17.5]
    lows = [15, 11, 14, 10, 12, 8, 11, 15]
    closes = [16, 15, 16, 10, 13, 9, 16, 17.2]
    df = pd.DataFrame({"timestamp": timestamps, "high": highs, "low": lows, "close": closes})
    
    tf = pd.Timedelta("1h")
    swings = find_swings(df, n=1, tf=tf)
    events = detect_bos_choch(df, swings, tf)
    
    assert events["label"].tolist() == ["INIT", "BOS", "CHoCH"]
    assert events["direction"].tolist() == ["down", "down", "up"]

def test_consumption_rule():
    timestamps = pd.date_range("2023-01-01", periods=8, freq="1h", tz="UTC")
    highs = [10, 8, 12, 15, 12, 16, 14, 12]
    closes = [9, 7, 11, 14, 11, 16, 13, 11]
    lows = [h - 1 for h in highs]
    df = pd.DataFrame({"timestamp": timestamps, "high": highs, "low": lows, "close": closes})
    
    tf = pd.Timedelta("1h")
    swings = find_swings(df, n=1, tf=tf)
    events = detect_bos_choch(df, swings, tf)
    
    assert len(events) == 1
    assert events.iloc[0]["broken_swing_price"] == 15.0

def test_dst_anchors():
    timestamps = pd.date_range("2023-03-10", "2023-03-14", freq="15min", tz="UTC")
    df1 = pd.DataFrame({"timestamp": timestamps, "open": 1, "high": 1, "low": 1, "close": 1})
    
    timestamps2 = pd.date_range("2023-11-03", "2023-11-07", freq="15min", tz="UTC")
    df2 = pd.DataFrame({"timestamp": timestamps2, "open": 1, "high": 1, "low": 1, "close": 1})
    
    df = pd.concat([df1, df2]).reset_index(drop=True)
    
    h4 = resample_to_tf(df, "4h")
    for _, row in h4.iterrows():
        ny_hour = row["timestamp"].tz_convert("America/New_York").hour
        assert ny_hour in (17, 21, 1, 5, 9, 13), f"Failed at {row['timestamp']} -> NY hour {ny_hour}"
        
    d1 = resample_to_tf(df, "1D")
    for _, row in d1.iterrows():
        ny_hour = row["timestamp"].tz_convert("America/New_York").hour
        assert ny_hour == 17, f"Failed at {row['timestamp']} -> NY hour {ny_hour}"

def test_truncation():
    random.seed(42)
    np.random.seed(42)
    n = 500
    timestamps = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    prices = np.cumsum(np.random.randn(n) * 10)
    df = pd.DataFrame({"timestamp": timestamps, "high": prices + 5, "low": prices - 5, "close": prices, "open": prices})
    
    tf_m15 = pd.Timedelta("15m")
    full_swings = find_swings(df, n=2, tf=tf_m15)
    full_events = detect_bos_choch(df, full_swings, tf_m15)
    
    for cut in [random.randint(50, n - 20) for _ in range(100)]:
        df_cut = df.iloc[:cut].reset_index(drop=True)
        cut_swings = find_swings(df_cut, n=2, tf=tf_m15)
        cut_events = detect_bos_choch(df_cut, cut_swings, tf_m15)
        
        cutoff_time = df_cut["timestamp"].iloc[-1] + tf_m15
        if full_events.empty: continue
        expected = full_events[full_events["time"] <= cutoff_time].reset_index(drop=True)
        
        try:
            pd.testing.assert_frame_equal(expected, cut_events)
        except AssertionError:
            print(f"\n--- FAILED at cut={cut} ---")
            print(f"Cutoff time: {cutoff_time}")
            print("Expected:")
            print(expected[["time", "label", "direction"]])
            print("Actual:")
            print(cut_events[["time", "label", "direction"]])
            raise

def test_truncation_h4_d1():
    random.seed(42)
    np.random.seed(42)
    n = 2000
    timestamps = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    prices = np.cumsum(np.random.randn(n) * 10)
    df = pd.DataFrame({"timestamp": timestamps, "high": prices + 5, "low": prices - 5, "close": prices, "open": prices})
    
    for rule, tf_str, n_swing in [("4h", "4h", 2), ("1D", "1D", 3)]:
        tf = pd.Timedelta(tf_str)
        full_resampled = resample_to_tf(df, rule)
        full_swings = find_swings(full_resampled, n=n_swing, tf=tf)
        full_events = detect_bos_choch(full_resampled, full_swings, tf)
        
        for cut in [random.randint(200, n - 200) for _ in range(50)]:
            df_cut = df.iloc[:cut].reset_index(drop=True)
            cut_resampled = resample_to_tf(df_cut, rule)
            cut_swings = find_swings(cut_resampled, n=n_swing, tf=tf)
            cut_events = detect_bos_choch(cut_resampled, cut_swings, tf)
            
            # FIXED: Add tf to cutoff_time so we compare against the CLOSE time
            cutoff_time = cut_resampled["timestamp"].max() + tf
            
            if full_events.empty: continue
            expected = full_events[full_events["time"] <= cutoff_time].reset_index(drop=True)
            
            try:
                pd.testing.assert_frame_equal(expected, cut_events)
            except AssertionError:
                print(f"\n--- FAILED at cut={cut} for {rule} ---")
                print(f"Cutoff time: {cutoff_time}")
                print("Expected:")
                print(expected[["time", "label", "direction"]])
                print("Actual:")
                print(cut_events[["time", "label", "direction"]])
                raise

def test_drop_incomplete_trailing_bar():
    """Generate 10 complete H4 bars (160 M15 bars) + 2 extra M15 bars."""
    start = pd.Timestamp("2023-01-01 17:00:00", tz="America/New_York")
    periods = 160 + 2
    timestamps = pd.date_range(start, periods=periods, freq="15min", tz="America/New_York")
    df = pd.DataFrame({
        "timestamp": timestamps.tz_convert("UTC"),
        "open": 1, "high": 1, "low": 1, "close": 1
    })
    
    res = resample_to_tf(df, "4h")
    assert len(res) == 10, f"Expected 10 bars, got {len(res)}"
