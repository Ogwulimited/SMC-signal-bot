import pytest
import pandas as pd
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
PAIRS = ["eurusd", "usdjpy"]

@pytest.fixture(params=PAIRS)
def h1(request):
    return pd.read_parquet(PROCESSED_DIR / f"{request.param}_h1.parquet")

def test_weekend_open(h1):
    # 1. Spot checks on clean weeks
    # Winter 2022-01-09 (expect 22:00 UTC)
    w1 = h1[h1["timestamp"] >= pd.Timestamp("2022-01-09", tz="UTC")].iloc[0]["timestamp"]
    assert w1.strftime("%H:%M") == "22:00", f"Winter 2022 failed: {w1}"
    
    # Winter 2024-01-07 (expect 22:00 UTC)
    w2 = h1[h1["timestamp"] >= pd.Timestamp("2024-01-07", tz="UTC")].iloc[0]["timestamp"]
    assert w2.strftime("%H:%M") == "22:00", f"Winter 2024 failed: {w2}"
    
    # Summer 2022-07-03 (expect 21:00 UTC)
    s1 = h1[h1["timestamp"] >= pd.Timestamp("2022-07-03", tz="UTC")].iloc[0]["timestamp"]
    assert s1.strftime("%H:%M") == "21:00", f"Summer 2022 failed: {s1}"
    
    # Summer 2024-07-07 (expect 21:00 UTC)
    s2 = h1[h1["timestamp"] >= pd.Timestamp("2024-07-07", tz="UTC")].iloc[0]["timestamp"]
    assert s2.strftime("%H:%M") == "21:00", f"Summer 2024 failed: {s2}"

def test_london_jump(h1):
    # London jump winter is 07:00 UTC (Jan 11, 2022), summer is 06:00 UTC (July 12, 2022)
    w_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2022-01-11").date()) & (h1["timestamp"].dt.hour == 7)]
    s_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2022-07-12").date()) & (h1["timestamp"].dt.hour == 6)]
    assert len(w_day) > 0, "Missing 07:00 UTC in Winter"
    assert len(s_day) > 0, "Missing 06:00 UTC in Summer"

def test_nfp_spike(h1):
    # NFP spike winter is 13:00 UTC (Jan 7, 2022), summer is 12:00 UTC (July 8, 2022)
    w_nfp = h1[(h1["timestamp"] == pd.Timestamp("2022-01-07 13:00:00", tz="UTC"))]
    s_nfp = h1[(h1["timestamp"] == pd.Timestamp("2022-07-08 12:00:00", tz="UTC"))]
    assert not w_nfp.empty, "Missing 13:00 UTC bar (containing Winter NFP release)"
    assert not s_nfp.empty, "Missing 12:00 UTC bar (containing Summer NFP release)"
