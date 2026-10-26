import numpy as np
import pandas as pd
import pytest
from src import config
from src.research import primitives
from src.research import zones
from conftest import _mk_df


def test_detect_breakers_bullish_basic():
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 9.5, 9.0, 10.8, 10.6, 10.7, 11.2, 11.3]
    h1_highs  = [10.2]*warmup_n + [11.0, 10.0, 9.6, 11.2, 10.95, 10.8, 11.3, 11.4, 11.5]
    h1_lows   = [9.8]*warmup_n  + [9.9, 9.3, 8.8, 8.9, 10.5, 10.55, 11.0, 11.1, 11.2]
    h1_closes = [10.0]*warmup_n + [10.5, 9.5, 9.0, 11.05, 10.6, 10.7, 11.2, 11.3, 11.4]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")
    tf_h1 = pd.Timedelta(hours=1)

    m15_opens  = [12.5, 12.1, 11.2, 10.3, 10.5, 11.8, 12.3, 12.8]
    m15_highs  = [12.6, 12.2, 11.3, 10.6, 12.0, 12.5, 13.0, 13.2]
    m15_lows   = [12.0, 11.0, 10.2, 10.1, 10.4, 11.7, 12.2, 12.7]
    m15_closes = [12.1, 11.2, 10.3, 10.5, 11.8, 12.3, 12.8, 13.0]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 19:00")
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
    assert row["swing_time"] == pd.Timestamp("2023-01-01 15:00:00", tz="UTC")
    assert row["swing_price"] == 11.0
    assert row["bos_time"] == pd.Timestamp("2023-01-01 17:00:00", tz="UTC")
    assert row["zone_index"] == 15
    assert row["zone_time"] == pd.Timestamp("2023-01-01 15:00:00", tz="UTC")
    assert row["zone_low"] == 9.9
    assert row["zone_high"] == 11.0
    assert row["failed_at"] == pd.Timestamp("2023-01-01 19:00:00", tz="UTC")
    assert row["fvg_overlap"] == True
    assert row["fvg_low"] == 10.95
    assert row["fvg_high"] == 11.0
    assert row["limit_price"] == pytest.approx(10.45)
    assert row["stop"] == pytest.approx(9.86)
    assert row["filled"] == True
    assert row["fill_time"] == pd.Timestamp("2023-01-01 19:45:00", tz="UTC")
    assert row["cancelled"] == False
    assert pd.isna(row["cancel_time"])
