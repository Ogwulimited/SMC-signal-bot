import pytest
import pandas as pd
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"

@pytest.fixture
def h1():
    return pd.read_parquet(PROCESSED_DIR / "eurusd_h1.parquet")

def test_weekend_open(h1):
    w_row = h1[h1["timestamp"] >= pd.Timestamp("2023-01-01", tz="UTC")].iloc[0]
    assert w_row["timestamp"].strftime("%H:%M") == "22:00"
    s_row = h1[h1["timestamp"] >= pd.Timestamp("2023-07-02", tz="UTC")].iloc[0]
    assert s_row["timestamp"].strftime("%H:%M") == "21:00"

def test_london_jump(h1):
    w_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2023-01-10").date()) & (h1["timestamp"].dt.hour == 7)]
    s_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2023-07-10").date()) & (h1["timestamp"].dt.hour == 6)]
    assert len(w_day) > 0, "Missing 07:00 UTC in Winter"
    assert len(s_day) > 0, "Missing 06:00 UTC in Summer"

def test_nfp_spike(h1):
    w_nfp = h1[(h1["timestamp"] == pd.Timestamp("2023-01-06 13:00:00", tz="UTC"))]
    s_nfp = h1[(h1["timestamp"] == pd.Timestamp("2023-07-07 12:00:00", tz="UTC"))]
    assert not w_nfp.empty, "Missing Winter NFP (13:30 UTC)"
    assert not s_nfp.empty, "Missing Summer NFP (12:30 UTC)"
