import pytest
import pandas as pd
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
# NOTE: eurnzd/audcad were the original intent here but are part of the
# 17-pair expansion, not built by the 11-pair workflow yet. Swapped for
# eurgbp/gbpjpy (same cohort diversity: usd major, jpy major, eur cross,
# jpy cross) so this test is valid under the 11-pair pipeline. Revisit
# once the 28-pair workflow (histdata.yml) is fully fixed and could add
# eurnzd/audcad back, possibly as a separate parametrized test file.
PAIRS = ["eurusd", "usdjpy", "eurgbp", "gbpjpy"]

@pytest.fixture(params=PAIRS)
def h1(request):
    return pd.read_parquet(PROCESSED_DIR / f"{request.param}_h1.parquet")

def test_weekend_open(h1):
    w1 = h1[h1["timestamp"] >= pd.Timestamp("2022-01-09", tz="UTC")].iloc[0]["timestamp"]
    assert w1.strftime("%H:%M") == "22:00", f"Winter 2022 failed: {w1}"
    s1 = h1[h1["timestamp"] >= pd.Timestamp("2022-07-03", tz="UTC")].iloc[0]["timestamp"]
    assert s1.strftime("%H:%M") == "21:00", f"Summer 2022 failed: {s1}"

def test_london_jump(h1):
    w_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2022-01-11").date()) & (h1["timestamp"].dt.hour == 7)]
    s_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2022-07-12").date()) & (h1["timestamp"].dt.hour == 6)]
    assert len(w_day) > 0, "Missing 07:00 UTC in Winter"
    assert len(s_day) > 0, "Missing 06:00 UTC in Summer"

def test_nfp_spike(h1):
    w_nfp = h1[(h1["timestamp"] == pd.Timestamp("2022-01-07 13:00:00", tz="UTC"))]
    s_nfp = h1[(h1["timestamp"] == pd.Timestamp("2022-07-08 12:00:00", tz="UTC"))]
    assert not w_nfp.empty, "Missing 13:00 UTC bar (Winter NFP)"
    assert not s_nfp.empty, "Missing 12:00 UTC bar (Summer NFP)"
