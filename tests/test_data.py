"""Data pipeline tests. Run with: pytest tests/test_data.py -v"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest
from datetime import datetime, timezone
from src.data.build_history import (
    load_m15, get_h1, get_h4, get_d1, get_weekly, get_monthly,
    bars_available_at, prior_day_high_low, prior_week_high_low, prior_month_high_low,
)

PAIRS = ["eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"]
TEST_PAIR = "eurusd"


def test_dst_winter():
    """First M15 bar after Friday close is within 17:00-17:15 NY (winter)."""
    m15 = load_m15(TEST_PAIR)
    winter_start = pd.Timestamp("2023-01-06 22:00:00", tz="UTC")
    winter_end = pd.Timestamp("2023-01-10 00:00:00", tz="UTC")
    subset = m15[(m15["timestamp"] >= winter_start) & (m15["timestamp"] <= winter_end)]
    if len(subset) == 0:
        pytest.skip("No winter data for EURUSD")
    first = subset.iloc[0]
    ny = first["timestamp"].tz_convert("America/New_York")
    assert ny.hour == 17 and ny.minute < 15, f"Winter first bar: {ny}"
    print(f"Winter first bar NY: {ny}")


def test_dst_summer():
    """First M15 bar after Friday close is within 17:00-17:15 NY (summer)."""
    m15 = load_m15(TEST_PAIR)
    summer_start = pd.Timestamp("2023-07-07 21:00:00", tz="UTC")
    summer_end = pd.Timestamp("2023-07-10 23:00:00", tz="UTC")
    subset = m15[(m15["timestamp"] >= summer_start) & (m15["timestamp"] <= summer_end)]
    if len(subset) == 0:
        pytest.skip("No summer data for EURUSD")
    first = subset.iloc[0]
    ny = first["timestamp"].tz_convert("America/New_York")
    assert ny.hour == 17 and ny.minute < 15, f"Summer first bar: {ny}"
    print(f"Summer first bar NY: {ny}")


def test_resample_h1():
    """Recompute 20 random H1 bars from M15 and compare."""
    m15 = load_m15(TEST_PAIR)
    h1 = get_h1(TEST_PAIR)
    import random
    random.seed(42)
    sample = random.sample(range(len(h1)), min(20, len(h1)))
    for idx in sample:
        row = h1.iloc[idx]
        start = row["open_time"]
        end = row["close_time"]
        subset = m15[(m15["timestamp"] >= start) & (m15["timestamp"] < end)]
        if len(subset) == 0:
            continue
        expected_open = subset["open"].iloc[0]
        expected_high = subset["high"].max()
        expected_low = subset["low"].min()
        expected_close = subset["close"].iloc[-1]
        assert abs(row["open"] - expected_open) < 1e-9
        assert abs(row["high"] - expected_high) < 1e-9
        assert abs(row["low"] - expected_low) < 1e-9
        assert abs(row["close"] - expected_close) < 1e-9


def test_anchors_h4():
    """H4 bars open at 17, 21, 01, 05, 09, 13 NY."""
    h4 = get_h4(TEST_PAIR)
    for _, row in h4.head(100).iterrows():
        ny = row["open_time"].tz_convert("America/New_York")
        assert ny.hour in (1, 5, 9, 13, 17, 21), f"Bad H4 hour: {ny}"


def test_anchors_d1():
    """D1 bars open at 17:00 NY."""
    d1 = get_d1(TEST_PAIR)
    for _, row in d1.head(100).iterrows():
        ny = row["open_time"].tz_convert("America/New_York")
        assert ny.hour == 17 and ny.minute == 0, f"Bad D1 open: {ny}"


def test_anchors_week():
    """Weekly bars open Sunday 17:00 NY."""
    wk = get_weekly(TEST_PAIR)
    for _, row in wk.head(20).iterrows():
        ny = row["open_time"].tz_convert("America/New_York")
        assert ny.weekday() == 6 and ny.hour == 17, f"Bad week open: {ny}"


def test_no_lookahead():
    """bars_available_at never returns a bar with close_time > t."""
    m15 = load_m15(TEST_PAIR)
    for t in ["2023-01-05 12:00:00", "2023-06-15 08:30:00", "2024-01-10 20:00:00"]:
        ts = pd.Timestamp(t, tz="UTC")
        available = bars_available_at(m15, ts)
        if len(available) > 0:
            assert (available["close_time"] <= ts).all(), f"Lookahead at {t}"


def test_prior_helpers():
    """Prior day/week/month return floats."""
    t = pd.Timestamp("2023-06-15 12:00:00", tz="UTC")
    h, l = prior_day_high_low(TEST_PAIR, t)
    assert h > l
    h, l = prior_week_high_low(TEST_PAIR, t)
    assert h > l
    h, l = prior_month_high_low(TEST_PAIR, t)
    assert h > l
