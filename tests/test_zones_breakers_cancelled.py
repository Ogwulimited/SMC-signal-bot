import numpy as np
import pandas as pd
import pytest
from src.research import zones
from conftest import _mk_df


def test_breaker_bullish_fvg_present_but_cancelled():
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 9.5, 9.0, 10.8, 10.6, 10.7, 11.2, 11.3, 9.8]
    h1_highs  = [10.2]*warmup_n + [11.0, 10.0, 9.6, 11.2, 10.95, 10.8, 11.3, 11.4, 11.5, 9.9]
    h1_lows   = [9.8]*warmup_n  + [9.9, 9.3, 8.8, 8.9, 10.5, 10.55, 11.0, 11.1, 11.2, 9.3]
    h1_closes = [10.0]*warmup_n + [10.5, 9.5, 9.0, 11.05, 10.6, 10.7, 11.2, 11.3, 11.4, 9.5]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")
    tf_h1 = pd.Timedelta(hours=1)

    m15_df = _mk_df([12.0]*28, [12.0]*28, [12.0]*28, [12.0]*28, freq="15min", start="2023-01-01 19:00")
    tf_m15 = pd.Timedelta(minutes=15)

    bos_events = pd.DataFrame([{
        "label": "BOS",
        "direction": "down",
        "time": h1_df["timestamp"].iloc[16] + tf_h1,
        "close": 9.5,
        "broken_swing_time": pd.NaT,
        "broken_swing_price": np.nan,
        "last_opposite_time": h1_df["timestamp"].iloc[15],
        "last_opposite_price": 11.0,
    }])
    bos_events["time"] = pd.to_datetime(bos_events["time"], utc=True)
    bos_events["last_opposite_time"] = pd.to_datetime(bos_events["last_opposite_time"], utc=True)

    result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_events)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["direction"] == "bullish"
    assert row["zone_low"] == 9.9
    assert row["zone_high"] == 11.0
    assert row["failed_at"] == pd.Timestamp("2023-01-01 19:00:00", tz="UTC")
    assert row["fvg_overlap"] == True
    assert row["fvg_low"] == 10.95
    assert row["fvg_high"] == 11.0
    assert row["limit_price"] == pytest.approx(10.975)
    assert row["stop"] == pytest.approx(9.86)
    assert row["filled"] == False
    assert pd.isna(row["fill_time"])
    assert row["cancelled"] == True
    assert row["cancel_time"] == pd.Timestamp("2023-01-02 01:00:00", tz="UTC")
