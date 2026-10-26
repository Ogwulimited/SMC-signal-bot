import numpy as np
import pandas as pd
import pytest
from src.research import zones
from conftest import _mk_df


def test_detect_breakers_bearish_basic():
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 10.5, 11.0, 9.2, 9.4, 9.3, 8.8, 8.7]
    h1_highs  = [10.2]*warmup_n + [10.1, 10.7, 11.2, 11.1, 9.5, 9.45, 9.9, 8.9, 8.8]
    h1_lows   = [9.8]*warmup_n  + [9.9, 9.95, 10.4, 9.8, 9.05, 9.3, 9.0, 8.6, 8.5]
    h1_closes = [10.0]*warmup_n + [9.95, 10.5, 11.05, 9.4, 9.3, 9.4, 8.8, 8.7, 8.6]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")
    tf_h1 = pd.Timedelta(hours=1)

    m15_opens  = [8.0, 8.4, 9.3, 10.2, 10.0, 8.7, 8.2, 7.7]
    m15_highs  = [8.1, 8.5, 9.4, 10.3, 10.5, 8.8, 8.3, 7.8]
    m15_lows   = [7.5, 8.3, 9.2, 9.7, 9.5, 8.2, 7.7, 7.6]
    m15_closes = [8.4, 9.3, 10.2, 10.0, 8.7, 8.2, 7.7, 7.5]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 19:00")
    tf_m15 = pd.Timedelta(minutes=15)

    bos_events = pd.DataFrame([{
        "label": "BOS",
        "direction": "up",
        "time": h1_df["timestamp"].iloc[16] + tf_h1,
        "close": 10.5,
        "broken_swing_time": pd.NaT,
        "broken_swing_price": np.nan,
        "last_opposite_time": h1_df["timestamp"].iloc[15],
        "last_opposite_price": 9.9,
    }])
    bos_events["time"] = pd.to_datetime(bos_events["time"], utc=True)
    bos_events["last_opposite_time"] = pd.to_datetime(bos_events["last_opposite_time"], utc=True)

    result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_events)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["direction"] == "bearish"
    assert row["swing_time"] == pd.Timestamp("2023-01-01 15:00:00", tz="UTC")
    assert row["swing_price"] == 9.9
    assert row["bos_time"] == pd.Timestamp("2023-01-01 17:00:00", tz="UTC")
    assert row["zone_index"] == 15
    assert row["zone_time"] == pd.Timestamp("2023-01-01 15:00:00", tz="UTC")
    assert row["zone_low"] == 9.9
    assert row["zone_high"] == 10.1
    assert row["failed_at"] == pd.Timestamp("2023-01-01 19:00:00", tz="UTC")
    assert row["fvg_overlap"] == False
    assert pd.isna(row["fvg_low"])
    assert pd.isna(row["fvg_high"])
    assert row["limit_price"] == pytest.approx(10.0)
    assert row["stop"] == pytest.approx(10.14)
    assert row["filled"] == True
    assert row["fill_time"] == pd.Timestamp("2023-01-01 20:00:00", tz="UTC")
    assert row["cancelled"] == False
    assert pd.isna(row["cancel_time"])
